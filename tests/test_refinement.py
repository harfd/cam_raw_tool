import copy
import hashlib
import json
import shutil
import time
from uuid import uuid4
from xml.etree import ElementTree as ET
import httpx
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend import ai_engine,settings
from backend.main import app
from backend.models import Refinement,RenderRequest
from backend.parameter_engine import build_recipe
from backend.refinement import merge_refinement,undo_refinement
from backend.segmentation import new_region
from backend.store import JOBS_DIR,save_job,get_job,connect
from backend.xmp import CRS,RDF
from tests.test_pipeline import METRICS,NEW_DECISION

def example_job(tmp_path):
    mask=np.zeros((80,120),np.uint8);mask[20:70,25:65]=255
    region=new_region(tmp_path,mask,'人物','subject','test')
    region.update(adjustments={'exposure':.3,'temperature':4,'saturation':-8},manual_adjustments=True,feather=0)
    return {'metrics':copy.deepcopy(METRICS),'decision':copy.deepcopy(NEW_DECISION),'regions':[region]}

def test_sparse_merge_keeps_all_unmentioned_manual_and_ai_values_and_mask(tmp_path):
    job=example_job(tmp_path)
    state=RenderRequest(strength=.65,overrides={'RedHue':17,'Saturation':-9},curve_overrides={'red':[{'x':0,'y':6},{'x':255,'y':250}]})
    before=build_recipe(job['metrics'],job['decision'],state)
    region=job['regions'][0]
    digest=hashlib.sha256((tmp_path/(region['id']+'.png')).read_bytes()).hexdigest()
    patch=Refinement(explanation='仅提亮人物',local=[{'region_id':region['id'],'reason':'只提亮人物','adjustments':{'exposure':.55}}])
    after,entry=merge_refinement(job,state,patch)
    actual=build_recipe(after['metrics'],after['decision'],RenderRequest.model_validate(after['edit_state']))
    assert actual['parameters']==before['parameters'] and actual['curves']==before['curves']
    assert after['regions'][0]['adjustments']=={**region['adjustments'],'exposure':.55}
    assert region['adjustments']['exposure']==.3
    assert len(entry['changes'])==1 and entry['changes'][0]['scope']=='local'
    assert hashlib.sha256((tmp_path/(region['id']+'.png')).read_bytes()).hexdigest()==digest

def test_sequential_final_values_not_rescaled_and_undo_preserves_mask_edits(tmp_path):
    job=example_job(tmp_path);state=RenderRequest(strength=.2)
    first,entry=merge_refinement(job,state,Refinement(explanation='降低暖色',parameters={'SplitToningHighlightSaturation':3}))
    first['refinement_history']=[entry]
    second,entry2=merge_refinement(first,RenderRequest.model_validate(first['edit_state']),Refinement(explanation='降低暖色',parameters={'SplitToningHighlightSaturation':1},curves={'blue':[{'x':0,'y':3},{'x':255,'y':255}]}))
    second['refinement_history']=[entry,entry2]
    result=build_recipe(second['metrics'],second['decision'],RenderRequest.model_validate(second['edit_state']))
    assert result['parameters']['SplitToningHighlightSaturation']==1
    assert result['curves']['blue']==[[0,3],[255,255]]
    restored=undo_refinement(second)
    assert restored['edit_state']==first['edit_state']
    assert len(restored['refinement_history'])==1

def test_invalid_patches_and_disabled_local_edits_are_atomic(tmp_path):
    job=example_job(tmp_path);original=copy.deepcopy(job);rid=job['regions'][0]['id']
    for patch in [Refinement(explanation='x',parameters={'Temperature':5000}),Refinement(explanation='x',parameters={'RedHue':101}),Refinement(explanation='x',parameters={'ParametricShadowSplit':65}),Refinement(explanation='x',local=[{'region_id':rid,'reason':'x','adjustments':{'exposure':99}}]),Refinement(explanation='x',local=[{'region_id':'a'*32,'reason':'x','adjustments':{'exposure':.5}}])]:
        with pytest.raises(ValueError):merge_refinement(job,RenderRequest(),patch)
        assert job==original
    local=Refinement(explanation='x',local=[{'region_id':rid,'reason':'x','adjustments':{'exposure':.5}}])
    for state in [RenderRequest(mode='style'),RenderRequest(include_local=False)]:
        with pytest.raises(ValueError):merge_refinement(job,state,local)
    job['regions'][0]['enabled']=False
    with pytest.raises(ValueError):merge_refinement(job,RenderRequest(),local)
    with pytest.raises(ValueError):Refinement(explanation='x',parameters={'RedHue':float('nan')})

def test_refinement_request_sends_current_state_and_images_and_repairs(monkeypatch,tmp_path):
    job=example_job(tmp_path);state=RenderRequest()
    image=tmp_path/'original.jpg';Image.new('RGB',(80,60),'green').save(image)
    calls=[];original=httpx.Client
    def handle(req):
        payload=json.loads(req.content);calls.append(payload)
        parts=payload['messages'][1]['content']
        assert sum(part['type']=='image_url' for part in parts)==3
        assert '当前方案' in str(payload) and 'parameters' in str(payload)
        patch={'explanation':'只改饱和度','parameters':{'Saturation':999 if len(calls)==1 else -12}}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(patch)}}]})
    monkeypatch.setattr(ai_engine.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handle)))
    diag=tmp_path/'diagnostic.json'
    patch=ai_engine.refine(image,image.read_bytes(),METRICS,'稍降饱和度',{'parameters':{'Saturation':-9}}, {'base_url':'https://api.deepseek.com','model':'deepseek-flash'},'secret-test-key',lambda p:merge_refinement(job,state,p),diag,mask_image=image.read_bytes())
    assert patch.parameters['Saturation']==-12 and len(calls)==2
    assert 'secret-test-key' not in diag.read_text('utf-8') and 'data:image' not in diag.read_text('utf-8')

@pytest.fixture
def saved_job():
    jid=uuid4().hex;directory=JOBS_DIR/jid;directory.mkdir()
    pixels=np.random.default_rng(2).integers(30,200,(80,120,3),dtype=np.uint8)
    for name in ['original.jpg','ai.jpg']:Image.fromarray(pixels).save(directory/name)
    job=example_job(directory)
    job.update(id=jid,filename='synthetic.NEF',created_at='test',status='complete',template={'version':'17.3','process_version':'15.4'},error=None)
    save_job(job)
    try:yield job
    finally:
        shutil.rmtree(directory)
        with connect() as db:db.execute('DELETE FROM jobs WHERE id=?',(jid,))

def wait_job(client,jid):
    for _ in range(100):
        job=client.get('/api/jobs/'+jid).json()
        if job['status']!='refining':return job
        time.sleep(.02)
    raise AssertionError('refinement did not finish')

def test_async_refine_export_persistence_failure_and_undo(monkeypatch,saved_job):
    job=saved_job;jid=job['id'];rid=job['regions'][0]['id']
    monkeypatch.setattr(settings,'api_key',lambda:'test-key')
    def refine(original,current,metrics,instruction,context,config,key,validate,**kw):
        assert context['parameters']['RedHue']==17
        assert context['enabled_regions'][0]['adjustments']['exposure']==.3
        assert current.startswith(b'\xff\xd8') and kw['mask_image'].startswith(b'\xff\xd8')
        patch=Refinement(explanation='仅人物提亮并减弱高光暖色',parameters={'SplitToningHighlightSaturation':2},local=[{'region_id':rid,'reason':'提亮人物','adjustments':{'exposure':.6}}])
        validate(patch);return patch
    monkeypatch.setattr(ai_engine,'refine',refine)
    state=RenderRequest(overrides={'RedHue':17}).model_dump()
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer test-session-token'
        response=client.post(f'/api/jobs/{jid}/refine',json={'instruction':'人物亮一点，减弱暖色','state':state})
        assert response.status_code==202
        result=wait_job(client,jid)
        assert result['error'] is None and result['decision']==job['decision']
        assert result['edit_state']['overrides']['RedHue']==17
        assert get_job(jid)['edit_state']==result['edit_state']
        exported=client.post(f'/api/jobs/{jid}/export',json={**result['edit_state'],'name':'incremental'})
        desc=ET.fromstring(exported.content).find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
        assert desc.get(f'{{{CRS}}}SplitToningHighlightSaturation')=='2'
        correction=desc.find(f'.//{{{CRS}}}MaskGroupBasedCorrections/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
        assert float(correction.get(f'{{{CRS}}}LocalExposure2012'))==.15
        def fail(*args,**kw):raise ValueError('连接失败')
        monkeypatch.setattr(ai_engine,'refine',fail)
        assert client.post(f'/api/jobs/{jid}/refine',json={'instruction':'test','state':result['edit_state']}).status_code==202
        failed=wait_job(client,jid)
        assert failed['edit_state']==result['edit_state'] and failed['regions']==result['regions']
        undone=client.post(f'/api/jobs/{jid}/refine/undo',json={}).json()
        assert undone['edit_state']==state
        assert undone['regions'][0]['adjustments']==job['regions'][0]['adjustments']

def test_refinement_blocks_concurrent_edits_and_needs_key(monkeypatch,saved_job):
    jid=saved_job['id'];monkeypatch.setattr(settings,'api_key',lambda:'')
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer test-session-token'
        assert client.post(f'/api/jobs/{jid}/refine',json={'instruction':'x','state':{}}).status_code==400
        saved_job['status']='refining';save_job(saved_job)
        assert client.post(f'/api/jobs/{jid}/analyze',json={}).status_code==409
        assert client.post(f'/api/jobs/{jid}/segment',json={}).status_code==409
        assert client.delete(f'/api/jobs/{jid}').status_code==409
