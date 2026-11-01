import copy
import io
from xml.etree import ElementTree as ET
import numpy as np
import pytest
from PIL import Image
from backend.ai_engine import parse_decision
from backend.models import RenderRequest
from backend.parameter_engine import build_recipe, COLORS, CURVE_FIELDS
from backend.preview import render
from backend.xmp import build_xmp, CRS, RDF
from tests.test_pipeline import METRICS, NEW_DECISION

TEMPLATE={'version':'17.3','process_version':'15.4'}

def advanced_decision():
    decision=copy.deepcopy(NEW_DECISION)
    decision['strategies']=[]
    look=decision['editing_plan']['look']
    look.update(calibration={'shadow_tint':8,'red_hue':12,'red_saturation':-8,'green_hue':-10,'green_saturation':6,'blue_hue':-20,'blue_saturation':16},
                parametric={'highlights':-20,'lights':12,'darks':-8,'shadows':16,'shadow_split':30,'midtone_split':55,'highlight_split':80},
                red_curve=[{'x':0,'y':0},{'x':128,'y':140},{'x':255,'y':255}],
                green_curve=[{'x':0,'y':0},{'x':128,'y':120},{'x':255,'y':255}],
                blue_curve=[{'x':0,'y':8},{'x':128,'y':132},{'x':255,'y':250}],
                colors=[{'color':color,'hue':10,'saturation':-20,'luminance':8} for color in COLORS])
    return decision

def test_ai_color_panels_map_to_adobe_fields_and_four_curve_sequences():
    import json
    decision=parse_decision(json.dumps(advanced_decision()),[])
    recipe=build_recipe(METRICS,decision,RenderRequest(strength=.5))
    params=recipe['parameters']
    assert params['RedHue']==6 and params['BlueHue']==-10  # calibration hue is a signed shift, not a hue angle
    assert params['ShadowTint']==4 and params['BlueSaturation']==8
    assert params['ParametricLights']==6 and params['ParametricHighlights']==-10
    assert params['ParametricShadowSplit']==30 and params['ParametricMidtoneSplit']==55
    for color in COLORS:
        assert params['HueAdjustment'+color]==5
        assert params['SaturationAdjustment'+color]==-10
        assert params['LuminanceAdjustment'+color]==4
    xml=build_xmp(params,'映射验证','photo',TEMPLATE,recipe['curve'],curves=recipe['curves'])
    desc=ET.fromstring(xml).find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
    assert desc.get(f'{{{CRS}}}RedHue')=='6'
    assert desc.get(f'{{{CRS}}}ParametricLights')=='6'
    for channel,field in CURVE_FIELDS.items():
        actual=[p.text for p in desc.findall(f'{{{CRS}}}{field}/{{{RDF}}}Seq/{{{RDF}}}li')]
        assert actual==[f'{x}, {y}' for x,y in recipe['curves'][channel]]
    assert recipe['curves']['red'][1]==[128,134]

def test_manual_controls_override_ai_without_strength_scaling_or_skin_clamp():
    decision=advanced_decision();decision['strategies']=['preserve_skin']
    points=[{'x':0,'y':5},{'x':100,'y':120},{'x':255,'y':250}]
    request=RenderRequest(strength=0,overrides={'RedHue':33,'HueAdjustmentOrange':22,'ParametricLights':45},curve_overrides={'red':points})
    recipe=build_recipe(METRICS,decision,request)
    assert recipe['parameters']['RedHue']==33
    assert recipe['parameters']['HueAdjustmentOrange']==22
    assert recipe['parameters']['ParametricLights']==45
    assert recipe['curves']['red']==[[p['x'],p['y']] for p in points]
    assert recipe['curves']['blue']==[[0,0],[128,128],[255,255]]
    reusable=build_recipe(METRICS,decision,request.model_copy(update={'mode':'style'}))
    assert 'Exposure2012' not in reusable['parameters'] and reusable['parameters']['RedHue']==33

def test_invalid_curve_splits_and_values_cannot_reach_export():
    for overrides in [{'RedHue':101},{'ParametricShadowSplit':60,'ParametricMidtoneSplit':50},{'ParametricHighlights':float('nan')}]:
        with pytest.raises(ValueError):build_recipe(METRICS,None,RenderRequest(overrides=overrides))
    for points in [[],[{'x':0,'y':0}], [{'x':0,'y':0},{'x':128,'y':200},{'x':255,'y':100}], [{'x':0,'y':0},{'x':256,'y':255}]]:
        with pytest.raises(ValueError):RenderRequest(curve_overrides={'blue':points})
    # A user may move several split positions together, relative to the AI's current split values.
    r=build_recipe(METRICS,advanced_decision(),RenderRequest(overrides={'ParametricShadowSplit':40}))
    assert r['parameters']['ParametricShadowSplit']==40

def test_old_ai_records_default_to_neutral_new_controls():
    recipe=build_recipe(METRICS,NEW_DECISION,RenderRequest(strength=1))
    assert recipe['parameters']['ShadowTint']==0 and recipe['parameters']['RedHue']==0
    assert recipe['parameters']['ParametricLights']==0 and recipe['parameters']['ParametricMidtoneSplit']==50
    assert recipe['curves']['red']==[[0,0],[255,255]]

def test_preview_responds_to_calibration_parametric_and_channel_curves(tmp_path):
    pixels=np.random.default_rng(12).integers(40,215,(64,64,3),dtype=np.uint8)
    path=tmp_path/'source.png';Image.fromarray(pixels).save(path)
    base=np.asarray(Image.open(io.BytesIO(render(path,{})))).astype(float)
    variants=[render(path,{'BlueHue':70,'RedSaturation':60,'ShadowTint':50}),render(path,{'ParametricLights':80}),render(path,{},curves={'blue':[[0,25],[128,170],[255,255]]})]
    for variant in variants:
        adjusted=np.asarray(Image.open(io.BytesIO(variant))).astype(float)
        assert np.abs(adjusted-base).mean()>1
