import copy
import io
import json
import zipfile
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from backend import acr_validation as acr
from backend.models import RenderRequest
from backend.parameter_engine import build_recipe
from backend.preview import load_source, render, detail, vignette_preview
from backend.raw_decoder import SRGB_ICC
from tests.test_pipeline import METRICS


def fixture(tmp_path):
    x=np.linspace(.1,.9,640,dtype=np.float32)
    rgb=np.broadcast_to(x[None,:,None],(400,640,3)).copy()
    np.save(tmp_path/'preview-srgb-v2.npy',rgb)
    # Poison JPEG proves that rendering does not use the 8-bit fallback.
    Image.new('RGB',(640,400),'red').save(tmp_path/'original.jpg')
    (tmp_path/'source.NEF').write_bytes(b'original unchanged')
    job={'id':'a'*32,'metrics':copy.deepcopy(METRICS),'regions':[],'template':{'version':'17.3','process_version':'15.4'}}
    return job,rgb


def png(image,icc=True):
    buf=io.BytesIO();Image.fromarray(np.uint8(np.rint(image*255))).save(buf,format='PNG',**({'icc_profile':SRGB_ICC} if icc else {}));return buf.getvalue()


def test_float_source_retains_sub_8bit_values_and_png_icc(tmp_path):
    job,rgb=fixture(tmp_path)
    source=load_source(tmp_path/'original.jpg')
    assert len(np.unique(source[:,:,0]))>256
    assert np.allclose(render(tmp_path/'original.jpg',{},return_array=True),rgb,atol=1e-6)
    output=Image.open(io.BytesIO(render(tmp_path/'original.jpg',{})))
    assert output.format=='PNG' and output.info['icc_profile']
    assert np.abs(load_source(tmp_path/'original.jpg',160)[:,:,0].mean()-.5)<1e-5


def test_snapshot_frozen_identity_comparison_and_provenance(tmp_path):
    job,rgb=fixture(tmp_path);state=RenderRequest(use_ai=False,strength=0,mode='style')
    record=acr.create(job,state,build_recipe(job['metrics'],None,state),tmp_path)
    root=tmp_path/'validation'/record['id'];before=(root/'reference.npy').read_bytes()
    report=acr.compare(root,(root/'reference.png').read_bytes(),acr_version='17.3',camera_profile='Adobe Color')
    assert report['rmse_255']<.51
    assert report['scopes'][0]['mae_255']<.51
    assert report['acr_version']=='17.3'
    original_signature=record['signature'];state.strength=.8
    assert acr.signature(job,state)!=original_signature
    assert (root/'reference.npy').read_bytes()==before
    with zipfile.ZipFile(root/'package.zip') as archive:
        assert archive.read('ACR-check.NEF')==b'original unchanged'
        assert b'PresetType' in archive.read('ACR-check.xmp')
        assert set(archive.namelist())=={'ACR-check.NEF','ACR-check.xmp','reference.png','snapshot.json','使用说明.txt'}


def test_comparison_rejects_missing_icc_size_ratio_and_bad_files(tmp_path):
    job,rgb=fixture(tmp_path);state=RenderRequest();record=acr.create(job,state,build_recipe(job['metrics'],None,state),tmp_path)
    root=tmp_path/'validation'/record['id']
    with pytest.raises(ValueError,match='ICC'):acr.compare(root,png(rgb,False))
    assert acr.compare(root,png(rgb,False),True)['color_basis'].startswith('用户确认')
    for arr,message in [(np.zeros((300,300,3)), '比例'),(np.zeros((200,320,3)),'尺寸')]:
        with pytest.raises(ValueError,match=message):acr.compare(root,png(arr))
    with pytest.raises(ValueError):acr.compare(root,b'not an image')


def test_positive_channel_and_luma_bias(tmp_path):
    job,rgb=fixture(tmp_path);state=RenderRequest(strength=0,mode='style');record=acr.create(job,state,build_recipe(job['metrics'],None,state),tmp_path)
    root=tmp_path/'validation'/record['id'];reference=np.load(root/'reference.npy')
    actual=reference.copy();actual[:,:,0]+=.04
    report=acr.compare(root,png(actual))
    assert report['rgb_bias_255'][0]>9
    assert abs(report['rgb_bias_255'][1])<.1
    assert report['scopes'][0]['luma_bias_255']>1.5


def test_full_resolution_detail_uses_raw_pixels_and_vignette_geometry(tmp_path):
    job,rgb=fixture(tmp_path)
    full=np.broadcast_to(np.linspace(.1,.9,1280,dtype=np.float32)[None,:,None],(800,1280,3)).copy()
    np.save(tmp_path/'full-srgb-v2.npy',np.uint16(np.rint(full*65535)))
    recipe={'parameters':{'PostCropVignetteAmount':-35},'curve':None,'curves':{},'white_balance':None}
    image=np.asarray(Image.open(io.BytesIO(detail(tmp_path,recipe,[],.8,.5,size=200))))/255
    left=round(.8*1280-100);top=300
    expected=vignette_preview(full,recipe['parameters'])[top:top+200,left:left+200]
    assert image.shape==(200,200,3)
    assert np.max(np.abs(image-expected))<.0021


def test_raw_transfer_is_explicit_srgb():
    from backend.raw_decoder import encode_srgb16
    linear=np.array([0,.0031308,.18,1],np.float32)
    encoded=encode_srgb16(np.uint16(np.rint(linear*65535)))/65535
    assert np.allclose(encoded,[0,.04045,.46136,1],atol=.0001)
