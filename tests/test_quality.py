import copy
import hashlib
import time
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import app
from backend import quality
from backend.models import RenderRequest
from backend.parameter_engine import build_recipe
from backend.refinement import undo_refinement
from backend.store import save_job,get_job,JOBS_DIR
from tests.test_pipeline import METRICS
from tests.test_refinement import saved_job

def gradient_fixture(tmp_path):
    ramp=np.linspace(.03,.94,240,dtype=np.float32)
    rgb=np.tile(ramp[None,:,None],(100,1,3));rgb[50:,:,1]*=.65;rgb[50:,:,2]*=.35
    Image.fromarray((rgb*255).astype(np.uint8)).save(tmp_path/'original.jpg',quality=98)
    return {'metrics':copy.deepcopy(METRICS),'decision':None,'regions':[]}

def aggressive_state(**kw):
    return RenderRequest(use_ai=False,strength=0,include_local=False,overrides={'Exposure2012':1.2,'Contrast2012':60,'Highlights2012':0,'Shadows2012':0,'Whites2012':0,'Saturation':80},**kw)

def test_original_white_black_and_dark_mood_are_not_new_failures(tmp_path):
    data=np.zeros((80,120,3),np.uint8);data[:30]=255;data[50:]=70
    Image.fromarray(data).save(tmp_path/'original.jpg',quality=100)
    job={'metrics':METRICS,'decision':None,'regions':[]}
    state=RenderRequest(strength=0,use_ai=False,overrides={k:0 for k in ['Exposure2012','Highlights2012','Shadows2012','Whites2012']})
    report=quality.check(job,state,tmp_path)
    assert report['status']=='ok' and report['issues']==[]
    assert report['scopes'][0]['metrics']['highlights']>.3 and report['scopes'][0]['metrics']['blacks']>.2
    result,entry=quality.correct(job,state,tmp_path,False)
    assert entry is None and result['quality_report']['correction']['evaluations']==1

def test_detects_and_reduces_new_risks_with_total_budgets_and_single_undo(tmp_path):
    job=gradient_fixture(tmp_path);state=aggressive_state()
    before=quality.check(job,state,tmp_path)
    assert before['status']=='attention' and before['score']>0
    original=copy.deepcopy(job)
    result,entry=quality.correct(job,state,tmp_path,False)
    assert job==original and entry is not None
    report=result['quality_report'];correction=report['correction']
    assert correction['score_after']<correction['score_before']
    assert 0<correction['iterations']<=4 and correction['evaluations']<=33
    initial=build_recipe(job['metrics'],None,state)
    final=build_recipe(job['metrics'],None,RenderRequest.model_validate(result['edit_state']))
    for key,budget in quality.BUDGETS.items():
        if key in initial['parameters']:assert abs(initial['parameters'][key]-final['parameters'][key])<=budget+1e-6
    for key,value in final['parameters'].items():
        if key not in quality.BUDGETS:assert value==initial['parameters'][key]
    assert final['curves']['red']==initial['curves']['red']
    assert all(t['score_after']<t['score_before'] for t in correction['trace'])
    result['refinement_history']=[entry]
    assert undo_refinement(result)['edit_state']==state.model_dump()

def test_protected_manual_parameters_and_curve_keep_exact_values(tmp_path):
    job=gradient_fixture(tmp_path)
    state=aggressive_state(curve_overrides={'rgb':[{'x':0,'y':0},{'x':120,'y':110},{'x':255,'y':255}]})
    result,entry=quality.correct(job,state,tmp_path,True)
    final_state=RenderRequest.model_validate(result.get('edit_state',state.model_dump()))
    final=build_recipe(job['metrics'],None,final_state)
    assert all(final['parameters'][k]==v for k,v in state.overrides.items())
    assert final['curves']['rgb']==[[p.x,p.y] for p in state.curve_overrides['rgb']]

def test_subject_metrics_manual_protection_and_mask_integrity(saved_job):
    job=saved_job;directory=JOBS_DIR/job['id'];rid=job['regions'][0]['id'];mask=directory/(rid+'.png')
    before=hashlib.sha256(mask.read_bytes()).hexdigest()
    job['regions'][0]['adjustments']['exposure']=2
    state=RenderRequest(strength=0,use_ai=False,overrides={k:0 for k in ['Exposure2012','Highlights2012','Shadows2012','Whites2012']})
    report=quality.check(job,state,directory)
    assert report['scopes'][1]['name']=='人物'
    result,entry=quality.correct(job,state,directory,True)
    assert result['regions'][0]['adjustments']==job['regions'][0]['adjustments']
    assert hashlib.sha256(mask.read_bytes()).hexdigest()==before

def test_quality_undo_api_no_key_stale_basis_and_busy_lock(monkeypatch,saved_job):
    job=saved_job;jid=job['id'];directory=JOBS_DIR/jid
    gradient_fixture(directory)
    from backend import settings
    monkeypatch.setattr(settings,'api_key',lambda:'')
    state=aggressive_state().model_dump()
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer test-session-token'
        checked=client.post(f'/api/jobs/{jid}/quality/check',json={'state':state})
        assert checked.status_code==200
        assert checked.json()['quality_report']['basis']['state']==state
        assert 'edit_state' not in checked.json()
        response=client.post(f'/api/jobs/{jid}/quality/correct',json={'state':state,'protect_manual':False})
        assert response.status_code==202
        for _ in range(300):
            result=client.get(f'/api/jobs/{jid}').json()
            if result['status']!='correcting':break
            time.sleep(.02)
        assert result['error'] is None and result['quality_report']['correction']['changed']
        assert result['refinement_history'][-1]['kind']=='auto_correction'
        assert result['quality_report']['basis']==quality.basis(result,RenderRequest.model_validate(result['edit_state']))
        from xml.etree import ElementTree as ET
        from backend.xmp import CRS,RDF
        exported=client.post(f'/api/jobs/{jid}/export',json={**result['edit_state'],'name':'自动修正验证'})
        desc=ET.fromstring(exported.content).find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
        for change in result['refinement_history'][-1]['changes']:
            if change['scope']=='global':assert float(desc.get(f"{{{CRS}}}{change['parameter']}"))==change['after']
        undone=client.post(f'/api/jobs/{jid}/refine/undo',json={}).json()
        assert undone['edit_state']==state
        assert undone['quality_report']['basis']!=quality.basis(undone,RenderRequest.model_validate(undone['edit_state']))
        job['status']='correcting';save_job(job)
        assert client.post(f'/api/jobs/{jid}/analyze',json={}).status_code==409
        assert client.post(f'/api/jobs/{jid}/segment',json={}).status_code==409
        assert client.delete(f'/api/jobs/{jid}').status_code==409

def test_correction_rejects_tradeoff_that_introduces_new_damage():
    zero={k:0 for k in quality.LIMITS}
    before={'score':1,'scopes':[{'region_id':None,'metrics':{**zero,'new_highlights':.2}}]}
    after={'score':.2,'scopes':[{'region_id':None,'metrics':{**zero,'new_highlights':.05,'new_blacks':.05}}]}
    assert not quality.improved(before,after)

def test_ai_hooks_check_after_edit_and_check_failure_keeps_ai_result(monkeypatch,saved_job):
    from backend.main import quality_after_ai
    state=RenderRequest()
    result=quality_after_ai(copy.deepcopy(saved_job),state,False)
    assert result['quality_report']['basis']==quality.basis(result,state)
    called=[]
    def correct(job,body,directory,protect):
        called.append(protect);return copy.deepcopy(job),None
    monkeypatch.setattr(quality,'correct',correct)
    result=quality_after_ai(copy.deepcopy(saved_job),state,True)
    assert called==[True] and result['decision']==saved_job['decision']
    def fail(*args):raise RuntimeError('check failure')
    monkeypatch.setattr(quality,'check',fail)
    result=quality_after_ai(copy.deepcopy(saved_job),state,False)
    assert result['decision']==saved_job['decision'] and result['regions']==saved_job['regions']
    assert result['quality_error'] and 'quality_report' not in result

def test_small_preview_candidate_must_pass_full_preview_recheck(monkeypatch,tmp_path):
    job=gradient_fixture(tmp_path);state=aggressive_state();evaluate=quality.Checker.evaluate;first={}
    def check(self,job,request):
        if self.max_dimension is None and job.get('edit_state'):
            rejected=copy.deepcopy(first['report']);rejected['score']+=1;return rejected
        report=evaluate(self,job,request)
        if self.max_dimension is None:first['report']=copy.deepcopy(report)
        return report
    monkeypatch.setattr(quality.Checker,'evaluate',check)
    result,entry=quality.correct(job,state,tmp_path,False)
    assert entry is None and 'edit_state' not in result
    assert not result['quality_report']['correction']['changed']
