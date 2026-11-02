"""Standalone Python 3.13 entry point. Imported only by the isolated film runtime."""
import json
import os
from pathlib import Path
import sys
import threading
import time


def watch_parent(pid):
    if os.name == 'nt':
        import ctypes
        api=ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.restype=ctypes.c_void_p
        api.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
        api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
        api.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=api.OpenProcess(0x100000,False,pid)
        if not handle:os._exit(1)
        api.WaitForSingleObject(handle,0xFFFFFFFF)
        api.CloseHandle(handle)
        os._exit(1)
    else:
        while os.getppid()==pid:time.sleep(1)
        os._exit(1)


def atomic_json(path, value):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    for attempt in range(10):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            if attempt==9:raise
            time.sleep(.02)


def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    threading.Thread(target=watch_parent,args=(request['parent_pid'],),daemon=True).start()
    directory=Path(request['output']);options=request['options']
    def stage(text):atomic_json(directory/'progress.json',{'stage':text})
    stage('加载胶片引擎；首次运行会编译计算内核')
    import numpy as np
    import rawpy
    import colour
    from PIL import Image,ImageCms,ImageFilter
    import tifffile
    from spektrafilm import init_params,simulate

    stage('从 NEF 解码高精度图像')
    preview=options['format']=='preview'
    with rawpy.imread(request['source']) as raw:
        rgb=raw.postprocess(use_camera_wb=True,no_auto_bright=True,half_size=preview,
                            output_color=rawpy.ColorSpace.ProPhoto,gamma=(1,1),output_bps=16)
    image=rgb.astype(np.float32)/65535
    del rgb
    if preview and max(image.shape[:2])>960:
        from skimage.transform import resize
        scale=960/max(image.shape[:2])
        image=resize(image,(round(image.shape[0]*scale),round(image.shape[1]*scale)),
                     preserve_range=True,anti_aliasing=True).astype(np.float32)
    baseline=colour.RGB_to_RGB(image,'ProPhoto RGB','sRGB',apply_cctf_decoding=False,apply_cctf_encoding=True)
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    def save_preview(array,path):
        photo=Image.fromarray(np.rint(np.clip(array,0,1)*255).astype(np.uint8))
        photo.thumbnail((1280,1280),Image.Resampling.LANCZOS)
        photo.save(path,quality=94,icc_profile=icc)
    save_preview(baseline,directory/'before.jpg');del baseline

    for mask in request['masks']:
        selection=Image.open(directory/mask['file']).convert('L')
        if mask['feather']:
            selection=selection.filter(ImageFilter.GaussianBlur(mask['feather']))
        selection=selection.resize((image.shape[1],image.shape[0]),Image.Resampling.BILINEAR)
        weight=np.asarray(selection,dtype=np.float32)/255
        image*=np.exp2(weight*mask['exposure'])[...,None]

    stage('模拟胶片、冲印和扫描')
    params=init_params(options['film'],options['paper'])
    # Reversal film is scanned directly; printing it onto negative paper would invert it.
    params.io.scan_film=params.film.is_positive
    params.io.input_color_space='ProPhoto RGB'
    params.io.input_cctf_decoding=False
    params.io.output_color_space='sRGB'
    params.io.output_cctf_encoding=True
    params.camera.auto_exposure=options['auto_exposure']
    params.camera.exposure_compensation_ev=options['exposure']
    params.enlarger.print_exposure=2**options['print_exposure']
    params.film_render.grain.active=options['grain']
    params.film_render.halation.active=options['halation']>0
    params.film_render.halation.halation_amount=options['halation']
    # The engine's own acceleration preserves its spatial and stochastic stages.
    params.settings.use_enlarger_lut=True
    params.settings.use_scanner_lut=True
    result=simulate(image,params,print_timings=True)
    del image
    if not np.isfinite(result).all():
        raise ValueError('Film engine returned non-finite pixels')
    clipped_fraction=float(np.mean(np.any((result<0)|(result>1),axis=-1)))
    result=np.clip(result,0,1)
    stage('写入成片及颜色配置')
    save_preview(result,directory/'preview.jpg')
    catalog=json.loads((Path(sys.executable).parent/'catalog.json').read_text(encoding='utf-8'))
    manifest={'engine':'spektrafilm','version':catalog['version'],'revision':catalog['revision'],
              'options':options,'color_space':'sRGB','source_precision':'16-bit linear ProPhoto RGB, floating-point simulation',
              'width':result.shape[1],'height':result.shape[0],'clipped_fraction':clipped_fraction,
              'local_exposure_masks':len(request['masks'])}
    manifest['print_applied']=not params.io.scan_film
    if options['format']=='tiff':
        filename='film-'+options['film']+'.tif'
        # Genuine 16-bit RGB, not an 8-bit preview promoted to a 16-bit container.
        tifffile.imwrite(directory/filename,np.rint(result*65535).astype(np.uint16),photometric='rgb',
                         metadata=None,description=json.dumps(manifest,ensure_ascii=True),
                         software='AI RAW Studio / spektrafilm',iccprofile=icc)
        bit_depth=16
    elif options['format']=='jpeg':
        filename='film-'+options['film']+'.jpg'
        Image.fromarray(np.rint(result*255).astype(np.uint8)).save(directory/filename,quality=96,subsampling=0,icc_profile=icc)
        bit_depth=8
    else:
        filename='preview.jpg';bit_depth=8
    manifest.update(filename=filename,bit_depth=bit_depth)
    atomic_json(directory/'result.json',manifest)


if __name__=='__main__':main()
