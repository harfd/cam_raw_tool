import hashlib
import json
import time
from pathlib import Path
from xml.etree import ElementTree as ET
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend import ai_engine, settings
from backend.models import Decision, RenderRequest
from backend.parameter_engine import build_parameters
from backend.xmp import CRS, RDF, build_xmp, template_info

ROOT = Path(__file__).resolve().parents[1]
METRICS = {'iso': 6400, 'sensor': {'saturated_fraction': .04}, 'preview': {'median_luminance': .01, 'shadow_fraction': .8, 'highlight_fraction': .2}}
DECISION = {'scene': '人像', 'subject': '人物', 'composition': '中心', 'lighting': '逆光', 'mood': '自然', 'recommended_style': 'natural', 'strategies': ['lift_shadows', 'preserve_skin', 'protect_highlights'], 'rationale': '保护肤色', 'crop_suggestion': '保留'}
NEW_DECISION = {**DECISION, 'editing_plan': {'correction': {'exposure_ev': .3, 'highlights': -45, 'shadows': 16, 'whites': -12}, 'look': {'contrast': 14, 'colors': [{'color':'Green','hue':8,'saturation':-30,'luminance':-8}], 'curve':[{'x':0,'y':5},{'x':128,'y':132},{'x':255,'y':250}]}, 'local': []}}

def test_high_iso_and_clipping_constraints():
    params, notes = build_parameters(METRICS, DECISION, RenderRequest())
    assert params['Exposure2012'] <= .2
    assert params['Shadows2012'] <= 20
    assert params['Highlights2012'] < 0
    assert any('ISO' in item for item in notes)

def test_reusable_export_omits_photo_data():
    params, _ = build_parameters(METRICS, DECISION, RenderRequest(style='film', mode='style'))
    data = build_xmp(params, '暖调 <测试> & 风格', 'style', template_info(ROOT / 'DSC_0002.xmp'))
    root = ET.fromstring(data)
    desc = root.find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
    assert desc.get(f'{{{CRS}}}PresetType') == 'Normal'
    assert len(desc.get(f'{{{CRS}}}UUID')) == 32
    assert desc.get(f'{{{CRS}}}ProcessVersion') == '15.4'
    for field in ['Exposure2012', 'Temperature', 'Tint', 'Highlights2012', 'Shadows2012', 'CameraProfileDigest']:
        assert f'{{{CRS}}}{field}' not in desc.attrib
    assert b'SerialNumber' not in data

def test_reject_invalid_sliders_and_unknown_ai():
    with pytest.raises(ValueError):
        build_parameters(METRICS, None, RenderRequest(overrides={'Exposure2012': 9}))
    with pytest.raises(ValueError):
        build_parameters(METRICS, None, RenderRequest(mode='style', overrides={'Exposure2012': 1}))
    with pytest.raises(ValueError):
        Decision.model_validate({**DECISION, 'strategies': ['run_code']})

def test_ai_image_request_and_bad_response(monkeypatch, tmp_path):
    image = tmp_path / 'ai.jpg'; image.write_bytes(b'jpeg-test-data')
    actual_client = httpx.Client
    def handler(request):
        body = json.loads(request.content)
        assert body['model'] == 'deepseek-flash'
        assert body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        assert request.headers['authorization'] == 'Bearer fake-test-key'
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(NEW_DECISION)}}]})
    monkeypatch.setattr(ai_engine.httpx, 'Client', lambda **kw: actual_client(transport=httpx.MockTransport(handler)))
    assert ai_engine.analyze(image, METRICS, '', {'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash'}, 'fake-test-key')['scene'] == '人像'
    monkeypatch.setattr(ai_engine.httpx, 'Client', lambda **kw: actual_client(transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    with pytest.raises(ValueError, match='API Key'):
        ai_engine.analyze(image, METRICS, '', {'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash'}, 'fake-test-key')

def test_real_nef_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, 'api_key', lambda: '')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT / 'DSC_0002.NEF', ROOT / 'DSC_0002.xmp']}
    with TestClient(app) as client:
        assert client.get('/api/jobs').status_code == 401
        client.headers['Authorization'] = 'Bearer test-session-token'
        with (ROOT / 'DSC_0002.NEF').open('rb') as raw, (ROOT / 'DSC_0002.xmp').open('rb') as xmp:
            response = client.post('/api/jobs', files={'raw': ('DSC_0002.NEF', raw), 'template': ('DSC_0002.xmp', xmp)})
        assert response.status_code == 202, response.text
        job_id = response.json()['id']
        for _ in range(120):
            job = client.get('/api/jobs/' + job_id).json()
            if job['status'] not in ('queued', 'decoding'): break
            time.sleep(.25)
        assert job['status'] == 'ready', job
        assert 'Z 30' in job['metadata']['camera']
        assert 0 <= job['metrics']['sensor']['saturated_fraction'] <= 1
        assert client.get(f'/api/jobs/{job_id}/original').content.startswith(b'\x89PNG')
        assert client.post(f'/api/jobs/{job_id}/analyze', json={}).status_code == 400
        for style in ['natural', 'cinematic', 'film']:
            for mode in ['photo', 'style']:
                body = {'style': style, 'mode': mode, 'strength': .7,
                        'overrides':{'RedHue':12,'ParametricLights':8,'HueAdjustmentAqua':-15},
                        'curve_overrides':{'blue':[{'x':0,'y':5},{'x':128,'y':135},{'x':255,'y':255}]}}
                preview = client.post(f'/api/jobs/{job_id}/preview', json=body)
                assert preview.status_code == 200, preview.text[:100]
                assert preview.content.startswith(b'\x89PNG')
                exported = client.post(f'/api/jobs/{job_id}/export', json={**body, 'name': '测试'})
                assert exported.status_code == 200
                desc=ET.fromstring(exported.content).find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
                assert desc.get(f'{{{CRS}}}RedHue')=='12'
                assert desc.get(f'{{{CRS}}}ParametricLights')=='8'
                assert [p.text for p in desc.findall(f'{{{CRS}}}ToneCurvePV2012Blue/{{{RDF}}}Seq/{{{RDF}}}li')]==['0, 5','128, 135','255, 255']
        assert client.delete(f'/api/jobs/{job_id}').status_code == 200
        assert client.get(f'/api/jobs/{job_id}').status_code == 404
    for name, digest in before.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
