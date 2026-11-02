"""Conservative display-preview checks and bounded, measured correction search."""
import copy
from datetime import datetime,timezone
import numpy as np
from PIL import Image
from .models import RenderRequest,Refinement
from .parameter_engine import build_recipe,RANGES
from .preview import render
from .refinement import merge_refinement
from .segmentation import selected_regions,load_mask

LIMITS={'new_highlights':.005,'new_blacks':.005,'new_saturation':.01,'over_lift':.05}
LABELS={'new_highlights':'新增亮部接近纯白','new_blacks':'新增暗部接近纯黑','new_saturation':'新增颜色接近饱和上限','over_lift':'暗部提亮幅度较大'}
WEIGHTS={'new_highlights':4,'new_blacks':3,'new_saturation':2,'over_lift':1}
BUDGETS={'Exposure2012':.3,'Highlights2012':20,'Whites2012':15,'Shadows2012':20,'Blacks2012':12,'Contrast2012':12,'Saturation':12,'Vibrance':12}
BUDGETS.update({'SaturationAdjustment'+c:10 for c in ['Red','Orange','Yellow','Green','Aqua','Blue','Purple','Magenta']})
LOCAL_BUDGETS={'exposure':.3,'highlights':20,'whites':15,'shadows':20,'blacks':12,'contrast':12,'saturation':12}

def basis(job,state):
    return {'state':state.model_dump(),'decision':job.get('decision'),
            'regions':[{k:r.get(k) for k in ['id','enabled','revision','feather','adjustments']} for r in job.get('regions',[])],
            'preview_version':job['metrics'].get('preview_version',1)}

def features(rgb):
    maximum=rgb.max(axis=2);minimum=rgb.min(axis=2)
    sat=(maximum-minimum)/np.maximum(maximum,1e-5)
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    return {'white':minimum>=.98,'black':maximum<=.02,'saturated':(sat>=.97)&(maximum>.25),
            'max':maximum,'min':minimum,'sat':sat,'linear_lum':linear@np.array([.2126,.7152,.0722],np.float32)}

def measures(reference,current,mask=None):
    weight=np.ones(reference['max'].shape,np.float32) if mask is None else mask.astype(np.float32)
    total=max(float(weight.sum()),1e-5)
    def fraction(condition):return float((condition*weight).sum()/total)
    ref_lum=reference['linear_lum'];cur_lum=current['linear_lum']
    ev=np.log2(np.maximum(cur_lum,1e-5)/np.maximum(ref_lum,1e-5))
    return {'highlights':fraction(current['white']),'blacks':fraction(current['black']),'saturation':fraction(current['saturated']),
            'new_highlights':fraction(current['white']&(reference['min']<.96)),
            'new_blacks':fraction(current['black']&(reference['max']>.04)),
            'new_saturation':fraction(current['saturated']&(reference['sat']<.90)),
            'over_lift':fraction((ref_lum>.003)&(ref_lum<.12)&(ev>1.5)),
            'mean_luminance':float((cur_lum*weight).sum()/total)}

class Checker:
    def __init__(self,job,state,directory,max_dimension=None):
        self.directory=directory
        self.max_dimension=max_dimension
        image=Image.open(directory/'original.jpg').convert('RGB')
        if max_dimension:image.thumbnail((max_dimension,max_dimension),Image.Resampling.LANCZOS)
        self.image=image
        self.original=np.asarray(image).astype(np.float32)/255
        self.reference=features(self.original)
        self.region_masks={r['id']:load_mask(directory,r) for r in selected_regions(job,state)}
        import cv2
        self.region_masks={k:cv2.resize(m,(image.width,image.height),interpolation=cv2.INTER_AREA) if m.shape!=self.original.shape[:2] else m for k,m in self.region_masks.items()}
        self.masks={r['id']:self.region_masks[r['id']] for r in selected_regions(job,state) if r.get('kind')=='subject' and r.get('area',0)>.002}

    def evaluate(self,job,state):
        recipe=build_recipe(job['metrics'],job.get('decision'),state)
        rgb=render(self.directory/'original.jpg',recipe['parameters'],recipe['curve'],selected_regions(job,state),self.directory,curves=recipe['curves'],return_array=True,max_dimension=self.max_dimension,source_image=self.image,region_masks=self.region_masks,white_balance=recipe['white_balance'])
        current=features(rgb)
        scopes=[{'name':'全图','region_id':None,'metrics':measures(self.reference,current)}]
        for r in selected_regions(job,state):
            if r['id'] in self.masks:
                scopes.append({'name':r['name'],'region_id':r['id'],'metrics':measures(self.reference,current,self.masks[r['id']])})
        issues=[]
        for scope in scopes:
            for key,threshold in LIMITS.items():
                if scope['metrics'][key]>threshold:
                    issues.append({'code':key,'label':LABELS[key],'scope':scope['name'],'region_id':scope['region_id'],
                                   'fraction':scope['metrics'][key],'threshold':threshold})
        score=sum(WEIGHTS[k]*max(0,s['metrics'][k]-v) for s in scopes for k,v in LIMITS.items())
        return {'time':datetime.now(timezone.utc).isoformat(),'basis':basis(job,state),'scopes':scopes,'issues':issues,
                'score':float(score),'status':'attention' if issues else 'ok',
                'limits':'基于本地近似预览检测新增风险，不代表 RAW 细节是否可恢复或 Camera Raw 的最终效果。'}

def check(job,state,directory):
    return Checker(job,state,directory).evaluate(job,state)

def improved(before,after):
    if after['score']>=before['score']-1e-5:return False
    # No trading a large new failure for a smaller score elsewhere.
    for old,new in zip(before['scopes'],after['scopes']):
        if any(new['metrics'][k]>old['metrics'][k]+(.005 if old['region_id'] else .002) for k in LIMITS):return False
    return True

def correction_patches(job,state,origin,origin_state,protect_manual,report):
    params=build_recipe(job['metrics'],job.get('decision'),state)['parameters']
    original_params=build_recipe(origin['metrics'],origin.get('decision'),origin_state)['parameters']
    codes={i['code'] for i in report['issues']}
    steps={}
    if 'new_highlights' in codes:steps.update(Exposure2012=-.1,Highlights2012=-8,Whites2012=-5)
    if 'new_blacks' in codes:steps.update(Shadows2012=6,Blacks2012=4)
    if 'new_saturation' in codes:steps.update(Saturation=-4,Vibrance=-4)
    if 'new_saturation' in codes:
        steps.update({k:-4 for k,v in params.items() if k.startswith('SaturationAdjustment') and v>0})
    if 'over_lift' in codes:
        if params.get('Exposure2012',0)>0:steps['Exposure2012']=-.1
        if params.get('Shadows2012',0)>0:steps['Shadows2012']=-6
        if params.get('Blacks2012',0)>0:steps['Blacks2012']=-4
    if 'new_blacks' in codes and params.get('Exposure2012',0)<0:steps['Exposure2012']=.1
    if ('new_highlights' in codes or 'new_blacks' in codes) and params.get('Contrast2012',0)>0:steps['Contrast2012']=-4
    for key,step in steps.items():
        if key not in params or protect_manual and key in origin_state.overrides:continue
        value=params[key]+step
        # Color reduction and exposure/shadow rollback stop at neutral.
        if key in ('Exposure2012','Saturation','Vibrance','Contrast2012') and value*params[key]<0:value=0
        if key in ('Saturation','Vibrance') and params[key]<=0:continue
        if key.startswith('SaturationAdjustment'):value=max(0,value)
        if key in ('Exposure2012',) and step<0 and params[key]<=0:continue
        if key in ('Shadows2012','Blacks2012') and 'over_lift' in codes and step<0:value=max(0,value)
        lo,hi=RANGES[key];budget=BUDGETS[key]
        value=round(max(lo,original_params[key]-budget,min(hi,original_params[key]+budget,value)),2)
        if value!=params[key]:yield Refinement(explanation='降低预览新增风险',parameters={key:value})
    # A small relaxation of the composite curve, preserving channel color curves.
    if {'new_highlights','new_blacks','over_lift'}.intersection(codes) and not(protect_manual and 'rgb' in origin_state.curve_overrides):
        recipe=build_recipe(job['metrics'],job.get('decision'),state)
        start=build_recipe(origin['metrics'],origin.get('decision'),origin_state)['curves']['rgb']
        points=[]
        for (x,y),(_,initial) in zip(recipe['curves']['rgb'],start):
            value=round(y+(x-y)*.2)
            value=max(initial-8,min(initial+8,value))
            points.append({'x':x,'y':max(0,min(255,value))})
        if [[p['x'],p['y']] for p in points]!=recipe['curves']['rgb']:
            try:yield Refinement(explanation='轻微缓和 RGB 总曲线',curves={'rgb':points})
            except ValueError:pass
    original_regions={r['id']:r for r in origin.get('regions',[])}
    for r in selected_regions(job,state):
        start=original_regions[r['id']]
        if protect_manual and start.get('manual_adjustments'):continue
        adjustments=r['adjustments'];local_steps={}
        if 'new_highlights' in codes:
            if adjustments.get('exposure',0)>0:local_steps['exposure']=-.1
            local_steps.update(highlights=-8,whites=-5)
        if 'new_blacks' in codes:local_steps.update(shadows=6,blacks=4)
        if 'new_saturation' in codes and adjustments.get('saturation',0)>0:local_steps['saturation']=-4
        if 'over_lift' in codes:
            for key,step in [('exposure',-.1),('shadows',-6),('blacks',-4)]:
                if adjustments.get(key,0)>0:local_steps[key]=step
        for key,step in local_steps.items():
            initial=start['adjustments'].get(key,0);current=adjustments.get(key,0)
            value=max(initial-LOCAL_BUDGETS[key],min(initial+LOCAL_BUDGETS[key],current+step))
            if step<0 and key in ('exposure','shadows','blacks','saturation') and current>0:value=max(0,value)
            if value==current:continue
            yield Refinement(explanation='降低局部预览新增风险',local=[{'region_id':r['id'],'reason':'自动检查后有限修正','adjustments':{key:round(value,2)}}])

def correct(job,state,directory,protect_manual=True):
    origin=copy.deepcopy(job);initial_state=state
    full_checker=Checker(job,state,directory)
    first=full_checker.evaluate(job,state)
    checker=Checker(job,state,directory,640) if first['issues'] else full_checker
    current=checker.evaluate(job,state) if first['issues'] else first
    working=copy.deepcopy(job);trace=[];evaluations=1
    if first['issues']:evaluations+=1
    for _ in range(4):
        if not current['issues']:break
        best=None
        for patch in correction_patches(working,state,origin,initial_state,protect_manual,current):
            if evaluations>=32:break  # reserve one full-preview verification
            try:
                candidate,_=merge_refinement(working,state,patch)
                next_state=RenderRequest.model_validate(candidate['edit_state'])
                report=checker.evaluate(candidate,next_state);evaluations+=1
            except ValueError:continue
            if improved(current,report) and (best is None or report['score']<best[2]['score']):best=(candidate,next_state,report)
        if best is None:break
        previous_score=current['score']
        working,state,current=best
        trace.append({'iteration':len(trace)+1,'score_before':previous_score,'score_after':current['score']})
    # Collapse accepted search steps into one reversible, absolute patch.
    start_recipe=build_recipe(origin['metrics'],origin.get('decision'),initial_state)
    end_recipe=build_recipe(working['metrics'],working.get('decision'),state)
    parameters={k:v for k,v in end_recipe['parameters'].items() if start_recipe['parameters'][k]!=v}
    curves={c:[{'x':x,'y':y} for x,y in points] for c,points in end_recipe['curves'].items() if start_recipe['curves'][c]!=points}
    local=[];start_regions={r['id']:r for r in origin.get('regions',[])}
    for r in working.get('regions',[]):
        changes={k:v for k,v in r['adjustments'].items() if start_regions[r['id']]['adjustments'].get(k,0)!=v}
        if changes:local.append({'region_id':r['id'],'reason':'自动效果检查后有限修正','adjustments':changes})
    changed=bool(parameters or curves or local)
    entry=None;result=copy.deepcopy(origin)
    if changed:
        result,entry=merge_refinement(origin,initial_state,Refinement(explanation='通过小步试算降低新增预览风险；保留色相、校准和选区范围。',parameters=parameters,curves=curves,local=local))
        entry.update(kind='auto_correction',instruction='效果检查与自动修正')
        for r in result.get('regions',[]):
            if any(c['scope']=='local' and c.get('region_id')==r['id'] for c in entry['changes']):
                r['adjustment_source']='效果检查自动修正'
                r['manual_adjustments']=start_regions[r['id']].get('manual_adjustments',False)
    final_state=RenderRequest.model_validate(result.get('edit_state',initial_state.model_dump())) if changed else initial_state
    if changed:
        verified=full_checker.evaluate(result,final_state);evaluations+=1
        if improved(first,verified):current=verified
        else:
            result=copy.deepcopy(origin);entry=None;changed=False;trace=[];final_state=initial_state;current=first
    else:current=first
    current['basis']=basis(result,final_state)
    current['correction']={'changed':changed,'iterations':len(trace),'evaluations':evaluations,'trace':trace,'search_max_dimension':640,'full_preview_verified':changed,'protect_manual':protect_manual,
                           'before_scopes':first['scopes'],'score_before':first['score'],'score_after':current['score'],
                           'reason':'已有限修正，仍有风险请人工确认。' if changed and current['issues'] else '已有限修正。' if changed else '当前未检测到新增风险。' if not first['issues'] else '在幅度限制和参数保护范围内，没有找到可验证的改善。'}
    result['quality_report']=current
    return result,entry
