import math
from .models import EditingPlan, RenderRequest, ParametricCurve, WhiteBalance

COLORS = ['Red','Orange','Yellow','Green','Aqua','Blue','Purple','Magenta']
STYLES = {
 'natural': {'label':'自然通透','params':{'Contrast2012':7,'Vibrance':12,'Saturation':-2,'Texture':5,'Clarity2012':3,'LuminanceAdjustmentOrange':5}, 'curve':[[0,0],[64,65],[128,130],[192,194],[255,255]]},
 'cinematic': {'label':'电影感','params':{'Contrast2012':18,'Vibrance':-4,'Saturation':-9,'Blacks2012':-12,'SaturationAdjustmentGreen':-20,'HueAdjustmentGreen':12,'SaturationAdjustmentYellow':-12,'SaturationAdjustmentBlue':-8,'LuminanceAdjustmentOrange':7,'SplitToningShadowHue':205,'SplitToningShadowSaturation':15,'SplitToningHighlightHue':42,'SplitToningHighlightSaturation':12,'SplitToningBalance':5}, 'curve':[[0,5],[48,38],[128,126],[200,210],[255,249]]},
 'film': {'label':'复古胶片','params':{'Contrast2012':-8,'Vibrance':-6,'Saturation':-12,'Blacks2012':10,'Clarity2012':-5,'SaturationAdjustmentGreen':-22,'SplitToningHighlightHue':45,'SplitToningHighlightSaturation':15,'SplitToningShadowHue':220,'SplitToningShadowSaturation':8,'GrainAmount':20,'GrainSize':25,'GrainFrequency':50}, 'curve':[[0,15],[48,48],[128,133],[200,203],[255,243]]},
}
RANGES = {k:(-100.,100.) for k in ['Contrast2012','Highlights2012','Shadows2012','Whites2012','Blacks2012','Texture','Clarity2012','Dehaze','Vibrance','Saturation','SplitToningBalance']}
for color in COLORS:
 for kind in ['Hue','Saturation','Luminance']:
  RANGES[f'{kind}Adjustment{color}'] = (-100.,100.)
RANGES.update(Exposure2012=(-2.,2.),GrainAmount=(0.,100.),GrainSize=(0.,100.),GrainFrequency=(0.,100.),ColorGradeGlobalHue=(0.,360.),ColorGradeGlobalSat=(0.,100.))
RANGES.update(Temperature=(2000.,50000.),Tint=(-150.,150.),ColorGradeMidtoneHue=(0.,360.),ColorGradeMidtoneSat=(0.,100.),ColorGradeBlending=(0.,100.),
              PostCropVignetteAmount=(-100.,100.),PostCropVignetteStyle=(1.,3.),PostCropVignetteMidpoint=(0.,100.),PostCropVignetteRoundness=(-100.,100.),PostCropVignetteFeather=(0.,100.),PostCropVignetteHighlightContrast=(0.,100.))
for band in ['Shadow','Midtone','Highlight','Global']:RANGES['ColorGrade'+band+'Lum']=(-100.,100.)
GRADE_MAP={'midtone_hue':'ColorGradeMidtoneHue','midtone_saturation':'ColorGradeMidtoneSat','midtone_luminance':'ColorGradeMidtoneLum',
           'shadow_luminance':'ColorGradeShadowLum','highlight_luminance':'ColorGradeHighlightLum','global_luminance':'ColorGradeGlobalLum','blending':'ColorGradeBlending'}
VIGNETTE_MAP={'amount':'PostCropVignetteAmount','style':'PostCropVignetteStyle','midpoint':'PostCropVignetteMidpoint','roundness':'PostCropVignetteRoundness','feather':'PostCropVignetteFeather','highlights':'PostCropVignetteHighlightContrast'}
CALIBRATION_MAP={'shadow_tint':'ShadowTint','red_hue':'RedHue','red_saturation':'RedSaturation','green_hue':'GreenHue','green_saturation':'GreenSaturation','blue_hue':'BlueHue','blue_saturation':'BlueSaturation'}
PARAMETRIC_MAP={'highlights':'ParametricHighlights','lights':'ParametricLights','darks':'ParametricDarks','shadows':'ParametricShadows','shadow_split':'ParametricShadowSplit','midtone_split':'ParametricMidtoneSplit','highlight_split':'ParametricHighlightSplit'}
for key in [*CALIBRATION_MAP.values(),'ParametricHighlights','ParametricLights','ParametricDarks','ParametricShadows']:
 RANGES[key]=(-100.,100.)
RANGES.update(ParametricShadowSplit=(10.,70.),ParametricMidtoneSplit=(20.,80.),ParametricHighlightSplit=(30.,90.))
CURVE_FIELDS={'rgb':'ToneCurvePV2012','red':'ToneCurvePV2012Red','green':'ToneCurvePV2012Green','blue':'ToneCurvePV2012Blue'}
for band in ['Shadow','Highlight']:
 RANGES[f'SplitToning{band}Hue']=(0.,360.)
 RANGES[f'SplitToning{band}Saturation']=(0.,100.)
PHOTO_ONLY={'Exposure2012','Highlights2012','Shadows2012','Whites2012','Temperature','Tint'}
CORRECTION_MAP={'exposure_ev':'Exposure2012','highlights':'Highlights2012','shadows':'Shadows2012','whites':'Whites2012'}
LOOK_MAP={'contrast':'Contrast2012','blacks':'Blacks2012','texture':'Texture','clarity':'Clarity2012','dehaze':'Dehaze','vibrance':'Vibrance','saturation':'Saturation','shadow_hue':'SplitToningShadowHue','shadow_saturation':'SplitToningShadowSaturation','highlight_hue':'SplitToningHighlightHue','highlight_saturation':'SplitToningHighlightSaturation','balance':'SplitToningBalance','grain':'GrainAmount','global_hue':'ColorGradeGlobalHue','global_saturation':'ColorGradeGlobalSat'}

def validate_parameters(params):
 for key,value in params.items():
  if key not in RANGES:
   raise ValueError(f'不支持的参数：{key}')
  if not math.isfinite(value) or not RANGES[key][0] <= value <= RANGES[key][1]:
   raise ValueError(f'参数超出范围：{key}')
  if key=='PostCropVignetteStyle' and value not in (1,2,3):raise ValueError('暗角样式必须为 1、2 或 3。')
 if any(key.startswith('Parametric') and key.endswith('Split') for key in params):
  ParametricCurve.model_validate({src:params[dest] for src,dest in PARAMETRIC_MAP.items() if dest in params})

def build_recipe(metrics, decision, request: RenderRequest):
 template=STYLES[request.style]
 params={key:0 for key in RANGES if key not in PHOTO_ONLY}
 params.update(GrainSize=25,GrainFrequency=50,ParametricShadowSplit=25,ParametricMidtoneSplit=50,ParametricHighlightSplit=75,ColorGradeBlending=50,
               PostCropVignetteStyle=1,PostCropVignetteMidpoint=50,PostCropVignetteFeather=50)
 mapping=[]
 notes=[f"{template['label']}，风格强度 {round(request.strength*100)}%"]
 def assign(key,value,source,reason,scale=False):
  if scale and key not in ('SplitToningShadowHue','SplitToningHighlightHue','ColorGradeGlobalHue','ColorGradeMidtoneHue','ColorGradeBlending','SplitToningBalance','GrainSize','GrainFrequency') and not key.endswith('Split'):
   value*=request.strength
  params[key]=round(value,2) if key=='Exposure2012' else round(value)
  mapping.append({'source':source,'parameter':key,'value':params[key],'reason':reason})
 for key,value in template['params'].items():
  assign(key,value,'风格模板',template['label'],True)
 curve=template['curve']
 curves={'red':[[0,0],[255,255]],'green':[[0,0],[255,255]],'blue':[[0,0],[255,255]]}
 raw_plan=(decision or {}).get('editing_plan') if request.use_ai else None
 plan=EditingPlan.model_validate(raw_plan) if raw_plan else None
 strategies=(decision or {}).get('strategies',[]) if request.use_ai else []
 if request.mode=='photo':
  # An uncalibrated LibRaw display preview is not an exposure meter for Adobe.
  preview=metrics['preview']
  exposure=max(-.2,min(.25,math.log2(.10/max(preview['median_luminance'],.008))*.12))
  correction={'Exposure2012':exposure,'Highlights2012':-min(40,12+preview['highlight_fraction']*80),'Shadows2012':min(24,preview['shadow_fraction']*35),'Whites2012':-5}
  if plan:
   correction={dest:getattr(plan.correction,src) for src,dest in CORRECTION_MAP.items()}
  elif request.use_ai and decision:
   if 'protect_highlights' in strategies: correction['Highlights2012']-=15
   if 'lift_shadows' in strategies: correction['Shadows2012']=min(32,correction['Shadows2012']+8)
  for key,value in correction.items():
   assign(key,value,'AI 基础纠正' if plan else '本地基础纠正','针对当前照片，不随风格强度缩放')
  saturated=metrics['sensor']['saturated_fraction']
  if saturated>.01 and params['Exposure2012']>.2:
   assign('Exposure2012',.2,'高光约束','传感器近饱和采样较多，限制全局提亮')
  if metrics.get('iso',0)>=3200:
   if params['Shadows2012']>20: assign('Shadows2012',20,'噪声约束','高 ISO 限制阴影提亮')
   if params['Exposure2012']>.5: assign('Exposure2012',.5,'噪声约束','高 ISO 限制曝光增益')
   notes.append('高 ISO 保守提亮，减少放大暗部噪声。')
 else:
  notes.append('通用风格省略照片基础纠正及所有固定坐标局部蒙版。')
 if plan and request.style==(decision or {}).get('recommended_style'):
  for src,dest in LOOK_MAP.items():
   assign(dest,getattr(plan.look,src),'AI 风格决策',src,True)
  for color in plan.look.colors:
   for src,prefix in [('hue','Hue'),('saturation','Saturation'),('luminance','Luminance')]:
    assign(prefix+'Adjustment'+color.color,getattr(color,src),'AI 颜色决策',color.color+' '+src,True)
  curve=[[p.x,p.y] for p in plan.look.curve]
  for src,dest in CALIBRATION_MAP.items():
   assign(dest,getattr(plan.look.calibration,src),'AI 校准决策',src,True)
  for src,dest in PARAMETRIC_MAP.items():
   assign(dest,getattr(plan.look.parametric,src),'AI 参数曲线决策',src,True)
  for src,dest in GRADE_MAP.items():assign(dest,getattr(plan.look,src),'AI 色彩分级',src,True)
  for src,dest in VIGNETTE_MAP.items():assign(dest,getattr(plan.look.vignette,src),'AI 暗角决策',src,src=='amount')
  for channel in curves:
   curves[channel]=[[p.x,p.y] for p in getattr(plan.look,channel+'_curve')]
  notes.append('AI 的明暗、HSL、校准、四通道点曲线、参数曲线和色彩分级目标已逐项写入参数。')
 elif plan:
  notes.append('已切换风格：使用当前风格模板，照片纠正和局部计划仍可应用。')
 elif decision and request.use_ai:
  if 'soften_contrast' in strategies: assign('Contrast2012',min(params['Contrast2012'],7*request.strength),'旧版 AI 策略','柔和对比')
  if 'restrain_color' in strategies: assign('Vibrance',min(params['Vibrance'],0),'旧版 AI 策略','控制整体色彩')
  if 'enhance_depth' in strategies: assign('Clarity2012',min(10,params['Clarity2012']+4*request.strength),'旧版 AI 策略','增加全局局部对比')
  notes.append('此记录来自旧版分析，请重新 AI 分析以获得颜色、曲线和局部参数。')
 reference=metrics.get('white_balance_reference',{'temperature':5500,'tint':0,'source':'估计参考值','estimated':True})
 wb=request.white_balance or (plan.correction.white_balance if plan and request.mode=='photo' else WhiteBalance())
 if request.mode=='style' and request.white_balance is not None and wb.mode!='preserve':raise ValueError('通用风格不能包含固定白平衡，请选择保持当前。')
 if request.mode=='style':wb=WhiteBalance()
 if wb.mode=='custom':
  assign('Temperature',wb.temperature,'手动白平衡' if request.white_balance is not None else 'AI 白平衡','绝对色温，不随风格强度缩放')
  assign('Tint',wb.tint,'手动白平衡' if request.white_balance is not None else 'AI 白平衡','色调，不随风格强度缩放')
 elif {'Temperature','Tint'}.intersection(request.overrides):raise ValueError('请先启用自定义白平衡，再调整色温和色调。')
 # Validate the combined split positions, so one split can be moved after another.
 validate_parameters({**params,**request.overrides})
 if request.mode=='style' and PHOTO_ONLY.intersection(request.overrides):
  raise ValueError('通用风格预设不能加入照片专属纠正参数。')
 for key,value in request.overrides.items(): assign(key,value,'手动微调','用户设置')
 if 'preserve_skin' in strategies:
  for color in ['Red','Orange']:
   key='HueAdjustment'+color
   if key not in request.overrides and abs(params[key])>5: assign(key,max(-5,min(5,params[key])),'肤色约束','限制红、橙色色相偏移；手动设置优先')
 validate_parameters(params)
 curves['rgb']=curve
 for channel,points in curves.items():
  source='AI 风格决策' if plan and request.style==decision.get('recommended_style') else '风格模板'
  curves[channel]=[[x,round(x+(y-x)*request.strength)] for x,y in points]
  if channel in request.curve_overrides:
   curves[channel]=[[p.x,p.y] for p in request.curve_overrides[channel]]
   source='手动曲线'
  mapping.append({'source':source,'parameter':CURVE_FIELDS[channel],'value':curves[channel],'reason':'手动曲线直接使用；AI 和模板曲线按强度插值'})
 white_balance={**wb.model_dump(),'reference':reference}
 if wb.mode=='custom':white_balance.update(temperature=params['Temperature'],tint=params['Tint'])
 mapping.append({'source':'白平衡设置','parameter':'WhiteBalance','value':wb.mode,'reason':'保持当前时不写入 XMP 白平衡；拍摄设置写入 As Shot；自定义写入 Custom'})
 return {'parameters':params,'curve':curves['rgb'],'curves':curves,'mapping':mapping,'notes':notes,'white_balance':white_balance}

def build_parameters(metrics,decision,request: RenderRequest):
 recipe=build_recipe(metrics,decision,request)
 return recipe['parameters'],recipe['notes']
