"""Frozen, local ACR comparisons. No numerical score implies Adobe equivalence."""
import hashlib
import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps
from .preview import render
from .quality import basis
from .segmentation import selected_regions
from .xmp import build_xmp
from .raw_decoder import SRGB_ICC


def signature(job,state):
    payload=basis(job,state)
    # Same pixels rendered through the precision cache invalidate older references.
    payload['renderer']='precision-srgb-v2'
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def create(job,state,recipe,directory):
    ident=uuid4().hex
    root=directory/'validation'/ident;root.mkdir(parents=True)
    try:
        regions=selected_regions(job,state)
        rgb=render(directory/'original.jpg',recipe['parameters'],recipe['curve'],regions,directory,
                   curves=recipe['curves'],white_balance=recipe['white_balance'],return_array=True)
        np.save(root/'reference.npy',rgb,allow_pickle=False)
        Image.fromarray(np.rint(rgb*255).astype(np.uint8)).save(root/'reference.png',icc_profile=SRGB_ICC)
        xmp=build_xmp(recipe['parameters'],'ACR 对照 '+ident[:8],state.mode,job['template'],recipe['curve'],regions,directory,curves=recipe['curves'],white_balance=recipe['white_balance'])
        (root/'ACR-check.xmp').write_bytes(xmp)
        record={'id':ident,'created_at':datetime.now(timezone.utc).isoformat(),'signature':signature(job,state),
                'decision':job.get('decision'),'state':state.model_dump(),'regions':basis(job,state)['regions'],'recipe':recipe,'template':job['template'],
                'reference_size':[rgb.shape[1],rgb.shape[0]],'renderer':'precision-srgb-v2',
                'source_sha256':hashlib.sha256((directory/'source.NEF').read_bytes()).hexdigest(),
                'xmp_sha256':hashlib.sha256(xmp).hexdigest()}
        (root/'snapshot.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        instructions='''ACR 对照验证（只操作副本）
1. 解压全部文件，在 Camera Raw 打开 ACR-check.NEF，通过“载入设置”载入 ACR-check.xmp。
2. 确认未附加其他预设；关闭自动调整、裁切、旋转、几何和镜头变形校正，保持原始画幅。
3. 记录实际 ACR 版本和相机配置文件。白平衡保持当前模式时，两个引擎的基础白平衡也可能不同。
4. 保存 JPEG/PNG/TIFF，选择 sRGB 并嵌入 ICC，原始比例，不加水印或输出锐化；推荐全尺寸或至少1600长边。
5. 在软件中为此快照导入实际成片。reference.png 是本地模拟，不是 ACR 成片。
6. 全局、RGB 各通道、亮部/暗部与差异图用于查找偏差，不代表审美评分或兼容性认证。
照片内容、方向、画幅和设置必须匹配。程序只检查比例，无法证明你导入了同一照片或相同设置。
导入成片按 ICC 转换到 sRGB 的8位显示像素后，缩小到本地参考尺寸比较。不要用截图代替成片。
局部蒙版和质感、颗粒算法仍是近似；本地预览与 Adobe 的相机配置文件、基础曲线不同。
'''
        with zipfile.ZipFile(root/'package.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            archive.write(directory/'source.NEF','ACR-check.NEF')
            for name in ['ACR-check.xmp','reference.png','snapshot.json']:archive.write(root/name,name)
            archive.writestr('使用说明.txt',instructions)
        return record
    except Exception:
        shutil.rmtree(root)
        raise


def compare(root,content,assume_srgb=False,acr_version='',camera_profile=''):
    if len(content)>150*1024*1024:raise ValueError('对照成片超过150 MB。')
    try:
        image=Image.open(io.BytesIO(content))
        if image.format not in ('JPEG','PNG','TIFF') or image.width*image.height>100_000_000:
            raise ValueError('请选择不超过一亿像素的 JPEG、PNG 或 TIFF 成片。')
        image=ImageOps.exif_transpose(image)
        if image.mode not in ('RGB','RGBA'):raise ValueError('对照成片必须为 RGB 彩色图像。')
        if image.mode=='RGBA' and image.getchannel('A').getextrema()!=(255,255):
            raise ValueError('成片包含透明像素，请导出不透明的 RGB 成片。')
        profile=image.info.get('icc_profile')
        if profile:
            image=ImageCms.profileToProfile(image.convert('RGB'),ImageCms.ImageCmsProfile(io.BytesIO(profile)),ImageCms.createProfile('sRGB'),outputMode='RGB')
            color_basis='嵌入 ICC 转换为 sRGB（8位显示像素）'
        elif assume_srgb:
            image=image.convert('RGB');color_basis='用户确认无 ICC 图像为 sRGB（8位显示像素）'
        else:raise ValueError('成片缺少 ICC。请嵌入色彩配置，或明确确认它是 sRGB。')
        reference=np.load(root/'reference.npy',allow_pickle=False)
        h,w=reference.shape[:2];original_size=list(image.size)
        if abs((image.width/image.height)/(w/h)-1)>.005:raise ValueError('成片比例与快照不符，请关闭裁切、旋转和几何变形后重新导出。')
        if image.width<w or image.height<h:raise ValueError('成片尺寸小于参考，请以至少参考尺寸或原尺寸重新导出。')
        image=image.resize((w,h),Image.Resampling.LANCZOS)
        actual=np.asarray(image).astype(np.float32)/255
    except ValueError:raise
    except Exception as exc:raise ValueError('无法读取图像或 ICC，请重新导出标准 RGB sRGB 成片。') from exc
    delta=actual-reference
    lum=lambda a:a@np.array([.2126,.7152,.0722],np.float32)
    ref_lum=lum(reference);diff_lum=lum(actual)-ref_lum
    de=np.linalg.norm(cv2.cvtColor(actual,cv2.COLOR_RGB2LAB)-cv2.cvtColor(reference,cv2.COLOR_RGB2LAB),axis=2)
    scopes=[]
    for name,mask in [('全图',np.ones((h,w),bool)),('暗部',ref_lum<.2),('中间调',(ref_lum>=.2)&(ref_lum<=.8)),('亮部',ref_lum>.8)]:
        if not np.any(mask):continue
        scopes.append({'name':name,'pixels':int(mask.sum()),'mae_255':float(np.abs(delta[mask]).mean()*255),
                       'luma_bias_255':float(diff_lum[mask].mean()*255),'delta_e76_mean':float(de[mask].mean())})
    record=json.loads((root/'snapshot.json').read_text('utf-8'))
    report={'snapshot_id':record['id'],'created_at':datetime.now(timezone.utc).isoformat(),
            'acr_version':acr_version[:100],'camera_profile':camera_profile[:200],
            'input_sha256':hashlib.sha256(content).hexdigest(),'input_size':original_size,'comparison_size':[w,h],
            'color_basis':color_basis,'rgb_bias_255':(delta.mean(axis=(0,1))*255).tolist(),
            'rmse_255':float(np.sqrt(np.mean(delta**2))*255),'delta_e76_p95':float(np.percentile(de,95)),
            'scopes':scopes,'limits':'统计差异，不是审美评分；未自动确认照片、设置或像素对齐。正偏差代表 ACR 更亮／该通道更多。'}
    image.save(root/'acr.png',icc_profile=SRGB_ICC)
    heat=cv2.applyColorMap(np.uint8(np.clip(de/30,0,1)*255),cv2.COLORMAP_INFERNO)[...,::-1]
    Image.fromarray(heat).save(root/'difference.png',icc_profile=SRGB_ICC)
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
