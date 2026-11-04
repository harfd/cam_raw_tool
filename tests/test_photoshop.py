import json
import shutil
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
import numpy as np
from fastapi.testclient import TestClient

from backend import acr_validation, main, photoshop
from backend.models import RenderRequest
from backend.parameter_engine import build_recipe
from backend.xmp import CRS, RDF
from backend.segmentation import new_region
from tests.test_acr_validation import fixture


@pytest.fixture
def setup(tmp_path, monkeypatch):
    job_id = 'a' * 32
    directory = tmp_path / job_id;directory.mkdir()
    job, _ = fixture(directory);job['status'] = 'ready'
    monkeypatch.setattr(photoshop, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(main, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(main, 'require_job', lambda ident: job if ident == job_id else (_ for _ in ()).throw(main.HTTPException(404)))
    monkeypatch.setattr(photoshop, 'catalog', lambda: {'available': True, 'message': 'test Photoshop'})
    monkeypatch.setattr(photoshop, '_active', None)
    queued = []
    monkeypatch.setattr(photoshop, '_executor', SimpleNamespace(submit=lambda *args: queued.append(args)))
    def fake_invoke(root):
        adobe = root / 'adobe'
        shutil.copy2(adobe / 'ACR-check.xmp', adobe / 'applied.xmp')
        shutil.copy2(root / 'reference.png', adobe / 'rendered.tif')
        return {'ok': True, 'photoshop_version': 'test', 'camera_raw_plugin': 'Camera Raw 17.3 - test fixture',
                'width': 640, 'height': 400, 'input_depth': 'BitsPerChannelType.SIXTEEN'}
    monkeypatch.setattr(photoshop, 'invoke', fake_invoke)
    return job, directory, queued


def test_automatic_render_poll_restore_cache_exclusivity_and_source_safety(setup):
    job, directory, queued = setup
    source = (directory / 'source.NEF').read_bytes()
    body = RenderRequest(use_ai=False).model_dump()
    with TestClient(main.app, headers={'Authorization': 'Bearer test-session-token'}) as client:
        prefix = '/api/jobs/' + job['id']
        first = client.post(prefix + '/validation/render', json=body)
        assert first.status_code == 202, first.text
        snapshot = first.json();root = directory / 'validation' / snapshot['id']
        assert not (root / 'package.zip').exists()
        assert snapshot['photoshop']['status'] == 'running' and photoshop.busy(job['id'])
        assert client.delete(prefix).status_code == 409
        assert client.post(prefix + '/validation/render', json=body).json()['id'] == snapshot['id']
        other = {**body, 'strength': .3}
        assert client.post(prefix + '/validation/render', json=other).status_code == 409
        assert len(list((directory / 'validation').iterdir())) == 1
        queued[0][0](*queued[0][1:])
        restored = client.get(prefix + '/validation').json()
        assert restored['photoshop']['status'] == 'complete' and not photoshop.busy()
        assert restored['report']['rmse_255'] < .51
        assert restored['report']['automation']['acr_version'] == '17.3'
        assert not (root / 'adobe' / 'rendered.tif').exists()
        assert (root / 'adobe' / 'ACR-check.NEF').read_bytes() == source
        assert (directory / 'source.NEF').read_bytes() == source
        assert client.post(prefix + '/validation/render', json=body).json()['id'] == snapshot['id']
        forced = client.post(prefix + '/validation/render?refresh=true', json=body).json()
        assert forced['id'] != snapshot['id']
        photoshop.recover()
        assert photoshop.state(directory / 'validation' / forced['id'])['status'] == 'failed'


def test_unavailable_and_failed_renderer_allow_retry_without_publishing_report(setup, monkeypatch):
    job, directory, queued = setup
    with TestClient(main.app, headers={'Authorization': 'Bearer test-session-token'}) as client:
        prefix = '/api/jobs/' + job['id']
        monkeypatch.setattr(photoshop, 'catalog', lambda: {'available': False, 'message': 'not installed'})
        assert client.post(prefix + '/validation/render', json={}).status_code == 400
        assert not (directory / 'validation').exists()
        monkeypatch.setattr(photoshop, 'catalog', lambda: {'available': True})
        monkeypatch.setattr(photoshop, 'invoke', lambda root: (_ for _ in ()).throw(ValueError('Photoshop busy')))
        snapshot = client.post(prefix + '/validation/render', json={}).json()
        queued[-1][0](*queued[-1][1:])
        failed = client.get(prefix + '/validation/' + snapshot['id']).json()
        assert failed['photoshop']['status'] == 'failed' and failed['photoshop']['error'] == 'Photoshop busy'
        assert 'report' not in failed and not photoshop.busy()
        assert client.post(prefix + '/validation/render', json={}).json()['id'] != snapshot['id']


def test_readback_rejects_ignored_parameters_curves_profile_and_wrong_frame(setup):
    job, directory, queued = setup
    state = RenderRequest(use_ai=False, white_balance={'mode': 'custom', 'temperature': 6100, 'tint': 8},
                          overrides={'Exposure2012': .8}, curve_overrides={'blue': [{'x': 0, 'y': 5}, {'x': 255, 'y': 255}]})
    record = acr_validation.create(job, state, build_recipe(job['metrics'], None, state), directory, package=False)
    root = directory / 'validation' / record['id'];adobe = root / 'adobe';adobe.mkdir()
    photoshop.sidecar(root / 'ACR-check.xmp', adobe / 'ACR-check.xmp')
    tree = ET.parse(adobe / 'ACR-check.xmp');desc = tree.find(f'.//{{{RDF}}}Description')
    assert desc.get(f'{{{CRS}}}PresetType') is None
    assert desc.get(f'{{{CRS}}}WhiteBalance') == 'Custom'
    assert desc.get(f'{{{CRS}}}CameraProfile') == 'Adobe Standard'
    result = photoshop.invoke(root)
    assert photoshop.verify(root, result)['camera_profile'] == 'Adobe Standard'
    for name, value in [('Exposure2012', '0'), ('CameraProfile', 'wrong')]:
        applied = ET.parse(adobe / 'ACR-check.xmp')
        applied.find(f'.//{{{RDF}}}Description').set(f'{{{CRS}}}{name}', value)
        applied.write(adobe / 'applied.xmp')
        with pytest.raises(ValueError, match=name): photoshop.verify(root, result)
    photoshop.invoke(root)
    with pytest.raises(ValueError, match='画幅'): photoshop.verify(root, {**result, 'width': 400})
    applied = ET.parse(adobe / 'applied.xmp')
    applied.find(f'.//{{{CRS}}}ToneCurvePV2012Blue/{{{RDF}}}Seq/{{{RDF}}}li').text = '0, 0'
    applied.write(adobe / 'applied.xmp')
    with pytest.raises(ValueError, match='曲线'): photoshop.verify(root, result)


def test_readback_rejects_missing_masks_changed_local_values_and_brush_positions(setup):
    job, directory, _ = setup
    mask=np.zeros((400,640),np.uint8);mask[100:250,100:300]=255
    region=new_region(directory,mask,'test','custom','test');region['adjustments'].update(exposure=.8,blue=10)
    job['regions']=[region];state=RenderRequest(use_ai=False)
    record=acr_validation.create(job,state,build_recipe(job['metrics'],None,state),directory,package=False)
    root=directory/'validation'/record['id'];adobe=root/'adobe';adobe.mkdir()
    photoshop.sidecar(root/'ACR-check.xmp',adobe/'ACR-check.xmp')
    result=photoshop.invoke(root)
    assert photoshop.verify(root,result)['verified_mask_nodes']>0
    applied=ET.parse(adobe/'applied.xmp')
    correction=applied.find(f'.//{{{CRS}}}MaskGroupBasedCorrections/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
    correction.set(f'{{{CRS}}}LocalExposure2012','0');applied.write(adobe/'applied.xmp')
    with pytest.raises(ValueError,match='局部设置'):photoshop.verify(root,result)
    photoshop.invoke(root);applied=ET.parse(adobe/'applied.xmp')
    seq=applied.find(f'.//{{{CRS}}}Dabs/{{{RDF}}}Seq');seq[1].text='d 0.99 0.99'
    applied.write(adobe/'applied.xmp')
    with pytest.raises(ValueError,match='笔刷位置'):photoshop.verify(root,result)
    photoshop.invoke(root);applied=ET.parse(adobe/'applied.xmp')
    group=applied.find(f'.//{{{CRS}}}MaskGroupBasedCorrections');group.clear();applied.write(adobe/'applied.xmp')
    with pytest.raises(ValueError,match='蒙版'):photoshop.verify(root,result)
