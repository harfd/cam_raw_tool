import copy
import json
from pathlib import Path
import httpx
import pytest
from backend import ai_engine
from backend.models import LocalAdjustments
from backend.segmentation import new_region
from backend.xmp import build_xmp, CRS, RDF
from xml.etree import ElementTree as ET
import numpy as np
from tests.test_pipeline import METRICS, NEW_DECISION

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/deepseek-local-whites.json').read_text('utf-8'))

def response(content, finish='stop'):
    return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':json.dumps(content,ensure_ascii=False)}}]})

def mock_client(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(ai_engine.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler)))

def test_actual_deepseek_response_with_local_whites_is_valid_and_exports(tmp_path):
    decision = ai_engine.parse_decision(json.dumps(FIXTURE['decision']), FIXTURE['regions'])
    target = next(t for t in decision['editing_plan']['local'] if 'whites' in t['adjustments'] and t['adjustments']['whites'])
    assert target['adjustments']['whites'] == -20
    region = new_region(tmp_path,np.full((30,40),255,np.uint8),'sky','sky','test')
    region['adjustments'] = target['adjustments']
    data = build_xmp({},'sky','photo',{'version':'17.3','process_version':'15.4'},regions=[region],directory=tmp_path)
    root = ET.fromstring(data)
    correction=root.find(f'.//{{{CRS}}}MaskGroupBasedCorrections/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
    assert float(correction.get(f'{{{CRS}}}LocalWhites2012')) == -.2
    assert float(correction.get(f'{{{CRS}}}LocalExposure2012')) == -.0625

def test_local_black_and_texture_ranges_and_mapping(tmp_path):
    params=LocalAdjustments(whites=-20,blacks=-12,texture=15)
    region=new_region(tmp_path,np.full((20,30),255,np.uint8),'r','custom','test')
    region['adjustments']=params.model_dump()
    root=ET.fromstring(build_xmp({},'r','photo',{'version':'17.3','process_version':'15.4'},regions=[region],directory=tmp_path))
    correction=root.find(f'.//{{{CRS}}}MaskGroupBasedCorrections/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
    assert float(correction.get(f'{{{CRS}}}LocalBlacks2012')) == -.12
    assert float(correction.get(f'{{{CRS}}}LocalTexture')) == .15
    with pytest.raises(ValueError):LocalAdjustments(whites=1000)

def test_schema_failure_repairs_once_and_logs_no_credentials(monkeypatch,tmp_path):
    calls=[]
    invalid=copy.deepcopy(NEW_DECISION)
    invalid['editing_plan']['look']['unsupported_parameter']=12
    def handler(request):
        payload=json.loads(request.content);calls.append(payload)
        return response(invalid if len(calls)==1 else NEW_DECISION)
    mock_client(monkeypatch,handler)
    image=tmp_path/'ai.jpg';image.write_bytes(b'private-image-bytes')
    diagnostic=tmp_path/'validation.json'
    result=ai_engine.analyze(image,METRICS,'',{'base_url':'https://api.deepseek.com','model':'deepseek-flash'},'secret-test-key',diagnostic_path=diagnostic)
    assert result['editing_plan'] is not None
    assert len(calls)==2
    assert 'unsupported_parameter' in calls[1]['messages'][-1]['content']
    assert calls[1]['max_tokens']>calls[0]['max_tokens']
    report=diagnostic.read_text('utf-8')
    assert 'secret-test-key' not in report and 'private-image-bytes' not in report and 'data:image' not in report
    assert [item['status'] for item in json.loads(report)['attempts']]==['invalid','valid']

def test_invalid_values_still_fail_after_one_repair(monkeypatch,tmp_path):
    invalid=copy.deepcopy(NEW_DECISION)
    invalid['editing_plan']['local']=[{'region_id':'a'*32,'reason':'test','adjustments':{'whites':999}}]
    calls=[]
    def handler(request):calls.append(1);return response(invalid)
    mock_client(monkeypatch,handler)
    image=tmp_path/'ai.jpg';image.write_bytes(b'jpeg')
    with pytest.raises(ValueError,match='第 1 个选区的白色色阶.*超过允许上限'):
        ai_engine.analyze(image,METRICS,'',{'base_url':'https://api.deepseek.com','model':'deepseek-flash'},'test-key',regions=[{'id':'a'*32}])
    assert len(calls)==2

def test_authentication_failure_is_not_retried(monkeypatch,tmp_path):
    calls=[]
    def handler(request):calls.append(1);return httpx.Response(401)
    mock_client(monkeypatch,handler)
    image=tmp_path/'ai.jpg';image.write_bytes(b'jpeg')
    with pytest.raises(ValueError,match='API Key'):
        ai_engine.analyze(image,METRICS,'',{'base_url':'https://api.deepseek.com','model':'deepseek-flash'},'test-key')
    assert len(calls)==1
