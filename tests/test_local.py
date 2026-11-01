import io
import json
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET
import cv2
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import app
from backend.models import RenderRequest, BrushStroke, Decision
from backend.parameter_engine import build_recipe
from backend.preview import local_adjust, render
from backend.segmentation import new_region, paint, segment, load_mask, apply_plan
from backend.mask_export import circle_cover
from backend.xmp import build_xmp, CRS, RDF
from backend.store import JOBS_DIR, save_job
from tests.test_pipeline import METRICS, NEW_DECISION

def test_explicit_ai_targets_reach_export():
    recipe=build_recipe(METRICS,NEW_DECISION,RenderRequest(style='natural',strength=1))
    assert recipe['parameters']['SaturationAdjustmentGreen']==-30
    assert recipe['parameters']['Highlights2012']==-45
    assert recipe['parameters']['Exposure2012']==.2 # sensor highlight safety limit
    assert recipe['curve']==[[0,5],[128,132],[255,250]]
    data=build_xmp(recipe['parameters'],'test','photo',{'version':'17.3','process_version':'15.4'},recipe['curve'])
    desc=ET.fromstring(data).find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
    assert desc.get(f'{{{CRS}}}SaturationAdjustmentGreen')=='-30'
    assert desc.find(f'{{{CRS}}}ToneCurvePV2012') is not None
    neutral=build_recipe(METRICS,NEW_DECISION,RenderRequest(style='natural',strength=0))
    assert neutral['parameters']['SaturationAdjustmentGreen']==0
    assert neutral['curve']==[[0,0],[128,128],[255,255]]

def test_local_adjustments_leave_outside_pixels_unchanged(tmp_path):
    image=np.full((100,150,3),80,np.uint8);Image.fromarray(image).save(tmp_path/'original.jpg')
    mask=np.zeros((100,150),np.uint8);mask[20:70,40:90]=255
    region=new_region(tmp_path,mask,'person','subject','test');region['feather']=0
    region['adjustments']['exposure']=1
    before=np.array(Image.open(io.BytesIO(render(tmp_path/'original.jpg',{}))))
    after=np.array(Image.open(io.BytesIO(render(tmp_path/'original.jpg',{},regions=[region],directory=tmp_path))))
    assert after[40,60].mean()>before[40,60].mean()+20
    assert np.abs(after[0:10].astype(float)-before[0:10]).max()<=1
    assert np.abs(after[:,120:].astype(float)-before[:,120:]).max()<=1

def test_brush_boundary_edit_and_circle_cover(tmp_path):
    mask=np.zeros((120,180),np.uint8);mask[20:80,30:100]=255
    region=new_region(tmp_path,mask,'r','custom','test')
    paint(tmp_path,region,BrushStroke(points=[(.8,.8)],radius=.025))
    assert load_mask(tmp_path,region,False)[96,144]>.5
    paint(tmp_path,region,BrushStroke(points=[(.8,.8)],radius=.04,erase=True))
    assert load_mask(tmp_path,region,False)[96,144]==0
    original=mask/255
    cover=circle_cover(original)
    reconstructed=np.zeros_like(mask)
    for radius,points in cover:
        for x,y in points:
            cv2.circle(reconstructed,(int(x*180),int(y*120)),max(0,round(radius*180)),1,-1)
    intersection=np.logical_and(original,reconstructed).sum()
    union=np.logical_or(original,reconstructed).sum()
    assert intersection/union>.98

def test_mask_export_is_local_and_not_semantic_placeholder(tmp_path):
    mask=np.zeros((80,120),np.uint8);mask[15:60,20:75]=255
    region=new_region(tmp_path,mask,'person','subject','test')
    region['adjustments'].update(exposure=.8,blue=15,temperature=-12)
    data=build_xmp({},'local','photo',{'version':'17.3','process_version':'15.4'},regions=[region],directory=tmp_path)
    root=ET.fromstring(data)
    group=root.find(f'.//{{{CRS}}}MaskGroupBasedCorrections/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
    assert float(group.get(f'{{{CRS}}}LocalExposure2012'))==.2
    assert float(group.get(f'{{{CRS}}}LocalTemperature'))==-.12
    assert group.find(f'{{{CRS}}}BlueCurve') is not None
    aggregate=group.find(f'{{{CRS}}}CorrectionMasks/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
    assert aggregate.get(f'{{{CRS}}}What')=='Mask/Aggregate'
    paint=aggregate.find(f'{{{CRS}}}Masks/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
    assert paint.get(f'{{{CRS}}}What')=='Mask/Paint'
    dabs=paint.find(f'{{{CRS}}}Dabs/{{{RDF}}}Seq')
    assert dabs[0].text=='f 1.0000'
    reference=ET.parse(Path(__file__).parent/'fixtures'/'acr17-brush.xmp').getroot()
    ref_group=reference.find(f'.//{{{CRS}}}CorrectionMasks/{{{RDF}}}Seq/{{{RDF}}}li/{{{RDF}}}Description')
    assert aggregate.get(f'{{{CRS}}}What')==ref_group.get(f'{{{CRS}}}What')
    assert set(ref_group.attrib)<=set(aggregate.attrib)
    assert b'Mask/Paint' in data and b'Dabs' in data and b'Mask/Image' not in data
    assert b'Exposure2012="0.8"' not in data
    with pytest.raises(ValueError):
        build_xmp({},'bad','style',{'version':'17.3','process_version':'15.4'},regions=[region],directory=tmp_path)

def test_invalid_curve_and_unknown_regions_rejected(tmp_path):
    invalid={**NEW_DECISION,'editing_plan':{**NEW_DECISION['editing_plan'],'look':{'curve':[{'x':0,'y':0},{'x':100,'y':150},{'x':255,'y':100}]}}}
    with pytest.raises(ValueError): Decision.model_validate(invalid)
    job={'regions':[],'decision':{'editing_plan':{'local':[{'region_id':uuid.uuid4().hex,'reason':'x','adjustments':{}}]}}}
    with pytest.raises(ValueError): apply_plan(job)

def test_real_model_and_mask_editor_api():
    job_id=uuid.uuid4().hex;directory=JOBS_DIR/job_id;directory.mkdir()
    # Reuse the real decoded sample created by the regression fixture directory.
    from backend.raw_decoder import decode
    source=Path(__file__).resolve().parents[1]/'DSC_0002.NEF'
    metadata,metrics,warnings=decode(source,directory)
    save_job({'id':job_id,'filename':'local-test.NEF','status':'ready','metadata':metadata,'metrics':metrics,'warnings':warnings,'template':{'version':'17.3','process_version':'15.4'}})
    with TestClient(app,headers={'Authorization':'Bearer test-session-token'}) as client:
        result=client.post(f'/api/jobs/{job_id}/segment');assert result.status_code==200,result.text
        regions=result.json()['regions']
        subject=next(r for r in regions if r['kind']=='subject')
        assert .01<subject['area']<.2
        mask=load_mask(directory,subject,False)
        assert mask[850,590]>.5 # painter's torso
        assert mask[780,890]<.5 # painted canvas was falsely selected before refinement
        region_id=subject['id']
        result=client.put(f'/api/jobs/{job_id}/regions/{region_id}',json={'adjustments':{'exposure':.75}})
        assert result.status_code==200
        result=client.post(f'/api/jobs/{job_id}/regions/{region_id}/refine',json={})
        assert result.status_code==200,result.text
        assert result.json()['regions'][0]['manual_adjustments']
        result=client.post(f'/api/jobs/{job_id}/regions/{region_id}/paint',json={'points':[[.1,.1],[.12,.1]],'radius':.02})
        assert result.status_code==200
        result=client.post(f'/api/jobs/{job_id}/regions/{region_id}/undo',json={})
        assert result.status_code==200
        exported=client.post(f'/api/jobs/{job_id}/export',json={'mode':'photo','name':'local-test'})
        assert exported.status_code==200,exported.text[:100]
        assert b'MaskGroupBasedCorrections' in exported.content
        general=client.post(f'/api/jobs/{job_id}/export',json={'mode':'style','name':'general'})
        assert b'MaskGroupBasedCorrections' not in general.content
        assert client.delete(f'/api/jobs/{job_id}').status_code==200
