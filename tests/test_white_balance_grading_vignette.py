import copy
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
import pytest
from PIL import Image
from backend.models import RenderRequest,Refinement,WhiteBalance,Decision
from backend.parameter_engine import build_recipe
from backend.preview import render
from backend.refinement import merge_refinement,undo_refinement
from backend.xmp import build_xmp,template_info,CRS,RDF
from tests.test_pipeline import METRICS,NEW_DECISION

TEMPLATE={'version':'17.3','process_version':'15.4'}

def plan():
    d=copy.deepcopy(NEW_DECISION)
    d['editing_plan']['correction']['white_balance']={'mode':'custom','temperature':6100,'tint':12}
    d['editing_plan']['look'].update(midtone_hue=205,midtone_saturation=20,midtone_luminance=10,shadow_luminance=8,highlight_luminance=-10,global_luminance=-8,blending=70,balance=15,
        vignette={'amount':-30,'style':2,'midpoint':40,'roundness':20,'feather':80,'highlights':35})
    return d

def export(recipe,mode='photo'):
    data=build_xmp(recipe['parameters'],'新增面板','photo' if mode=='photo' else 'style',TEMPLATE,recipe['curve'],curves=recipe['curves'],white_balance=recipe['white_balance'])
    return ET.fromstring(data).find(f'{{{RDF}}}RDF/{{{RDF}}}Description')

def test_ai_fields_scale_correctly_and_export_native_attributes():
    d=Decision.model_validate(plan()).model_dump()
    r=build_recipe(METRICS,d,RenderRequest(strength=.4));p=r['parameters'];xml=export(r)
    assert p['Temperature']==6100 and p['Tint']==12
    assert xml.get(f'{{{CRS}}}WhiteBalance')=='Custom'
    assert p['ColorGradeMidtoneHue']==205 and p['ColorGradeMidtoneSat']==8 and p['ColorGradeMidtoneLum']==4
    assert p['ColorGradeBlending']==70 and p['SplitToningBalance']==15
    assert p['PostCropVignetteAmount']==-12 and p['PostCropVignetteStyle']==2
    assert p['PostCropVignetteMidpoint']==40 and p['PostCropVignetteFeather']==80 and p['PostCropVignetteHighlightContrast']==35
    for key in ['Temperature','Tint','ColorGradeShadowLum','ColorGradeMidtoneLum','ColorGradeHighlightLum','ColorGradeGlobalLum','PostCropVignetteAmount','PostCropVignetteStyle']:
        assert float(xml.get(f'{{{CRS}}}{key}'))==p[key]
    reusable=build_recipe(METRICS,d,RenderRequest(mode='style',strength=.4));xml=export(reusable,'style')
    assert xml.get(f'{{{CRS}}}WhiteBalance') is None and 'Temperature' not in reusable['parameters']
    assert float(xml.get(f'{{{CRS}}}PostCropVignetteAmount'))==-12

def test_white_balance_modes_validation_and_manual_priority():
    for mode,expected in [('preserve',None),('as_shot','As Shot'),('custom','Custom')]:
        r=build_recipe(METRICS,plan(),RenderRequest(white_balance=WhiteBalance(mode=mode,temperature=6400,tint=-8),strength=0))
        xml=export(r)
        assert xml.get(f'{{{CRS}}}WhiteBalance')==expected
        assert ('Temperature' in r['parameters'])==(mode=='custom')
        if mode=='custom':assert r['parameters']['Temperature']==6400 and r['parameters']['Tint']==-8
    for values in [{'temperature':1999},{'temperature':50001},{'tint':151},{'tint':float('nan')}]:
        with pytest.raises(ValueError):WhiteBalance(**values)
    with pytest.raises(ValueError):build_recipe(METRICS,None,RenderRequest(mode='style',white_balance=WhiteBalance(mode='custom')))
    with pytest.raises(ValueError):build_recipe(METRICS,None,RenderRequest(overrides={'PostCropVignetteStyle':1.5}))
    with pytest.raises(ValueError):build_recipe(METRICS,None,RenderRequest(overrides={'Temperature':6200}))

def test_template_white_balance_reference_is_used_only_for_as_shot(tmp_path):
    file=tmp_path/'reference.xmp'
    def write(mode):file.write_text(f'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="{RDF}" xmlns:crs="{CRS}"><rdf:RDF><rdf:Description crs:ProcessVersion="15.4" crs:WhiteBalance="{mode}" crs:Temperature="5150" crs:Tint="+15"/></rdf:RDF></x:xmpmeta>','utf-8')
    write('As Shot');reference=template_info(file)['white_balance_reference']
    assert reference['temperature']==5150 and reference['tint']==15 and not reference['estimated']
    write('Custom');assert 'white_balance_reference' not in template_info(file)

def test_incremental_white_balance_grading_vignette_preserves_other_values_and_undo():
    job={'metrics':METRICS,'decision':NEW_DECISION,'regions':[]};state=RenderRequest(overrides={'RedHue':17})
    initial=build_recipe(METRICS,NEW_DECISION,state)
    patch=Refinement(explanation='调整白平衡和中间调，添加柔和暗角',white_balance=WhiteBalance(mode='custom',temperature=6200,tint=8),parameters={'ColorGradeMidtoneLum':12,'PostCropVignetteAmount':-18})
    result,entry=merge_refinement(job,state,patch)
    r=build_recipe(METRICS,NEW_DECISION,RenderRequest.model_validate(result['edit_state']))
    assert r['parameters']['Temperature']==6200 and r['parameters']['RedHue']==17
    assert r['parameters']['ColorGradeMidtoneLum']==12 and r['parameters']['PostCropVignetteAmount']==-18
    assert r['curves']==initial['curves']
    result['refinement_history']=[entry]
    assert undo_refinement(result)['edit_state']==state.model_dump()
    updated,second=merge_refinement(result,RenderRequest.model_validate(result['edit_state']),Refinement(explanation='再暖一点',parameters={'Temperature':6500}))
    final=build_recipe(METRICS,NEW_DECISION,RenderRequest.model_validate(updated['edit_state']))
    assert final['parameters']['Temperature']==6500 and final['parameters']['Tint']==8
    assert updated['edit_state']['white_balance']['mode']=='custom'
    restored,_=merge_refinement(updated,RenderRequest.model_validate(updated['edit_state']),Refinement(explanation='恢复拍摄白平衡',white_balance=WhiteBalance(mode='as_shot')))
    r=build_recipe(METRICS,NEW_DECISION,RenderRequest.model_validate(restored['edit_state']))
    assert 'Temperature' not in r['parameters'] and r['white_balance']['mode']=='as_shot'
    with pytest.raises(ValueError):Refinement(explanation='冲突',white_balance=WhiteBalance(mode='custom'),parameters={'Tint':10})

def test_preview_white_balance_and_all_grading_dimensions_change_pixels(tmp_path):
    path=tmp_path/'original.png'
    ramp=np.tile(np.linspace(.08,.9,150,dtype=np.float32)[None,:,None],(100,1,3))
    Image.fromarray((ramp*255).astype(np.uint8)).save(path)
    base=render(path,{},return_array=True)
    wb={'reference':{'temperature':5500,'tint':0}}
    equal=render(path,{'Temperature':5500,'Tint':0},white_balance=wb,return_array=True)
    assert np.allclose(equal,base,atol=1e-6)
    warm=render(path,{'Temperature':7000,'Tint':0},white_balance=wb,return_array=True)
    assert warm[...,0].mean()>warm[...,2].mean()
    tint=render(path,{'Temperature':5500,'Tint':60},white_balance=wb,return_array=True)
    assert tint[...,1].mean()<tint[...,0].mean()
    for params in [{'ColorGradeMidtoneLum':35},{'ColorGradeShadowLum':25},{'ColorGradeHighlightLum':-25},{'ColorGradeGlobalLum':15},{'ColorGradeMidtoneHue':120,'ColorGradeMidtoneSat':40}]:
        result=render(path,params,return_array=True)
        assert np.abs(result-base).mean()>.005
    colors={'SplitToningShadowHue':240,'SplitToningShadowSaturation':40,'SplitToningHighlightHue':40,'SplitToningHighlightSaturation':40,'ColorGradeMidtoneHue':120,'ColorGradeMidtoneSat':25}
    a=render(path,{**colors,'ColorGradeBlending':0},return_array=True)
    b=render(path,{**colors,'ColorGradeBlending':100},return_array=True)
    c=render(path,{**colors,'SplitToningBalance':80},return_array=True)
    assert np.abs(a-b).mean()>.003 and np.abs(b-c).mean()>.003

def test_vignette_preview_edges_midpoint_feather_roundness_and_styles(tmp_path):
    path=tmp_path/'flat.png';Image.new('RGB',(180,120),(180,180,180)).save(path)
    neutral=render(path,{},return_array=True)
    params={'PostCropVignetteAmount':-50,'PostCropVignetteStyle':1,'PostCropVignetteFeather':60}
    dark=render(path,params,return_array=True)
    assert np.allclose(dark[60,90],neutral[60,90]) and dark[0,0].mean()<neutral[0,0].mean()
    light=render(path,{'PostCropVignetteAmount':50},return_array=True)
    assert light[0,0].mean()>neutral[0,0].mean()
    protected=render(path,{**params,'PostCropVignetteHighlightContrast':100},return_array=True)
    assert protected[0,0].mean()>dark[0,0].mean()
    for changed in [{'PostCropVignetteMidpoint':0},{'PostCropVignetteFeather':0},{'PostCropVignetteRoundness':100},{'PostCropVignetteStyle':2},{'PostCropVignetteStyle':3}]:
        variant=render(path,{**params,**changed},return_array=True)
        assert np.abs(variant-dark).mean()>.003
