"""Sparse, absolute edits to the current rendered state. Mask pixels never change."""
import copy
from datetime import datetime, timezone
from .models import Refinement, RenderRequest, LocalAdjustments
from .parameter_engine import build_recipe, validate_parameters, PHOTO_ONLY
from .segmentation import selected_regions

def context_images(job,state,recipe,current_image,directory):
    import io
    import numpy as np
    from PIL import Image,ImageDraw
    from .parameter_engine import RANGES
    from .segmentation import region_summary,load_mask
    regions=selected_regions(job,state)
    image=Image.open(io.BytesIO(current_image)).convert('RGB')
    summaries=[]
    palette=['#e88a80','#79b9e2','#8dcd92','#c3a2df','#dfbd73','#77cec2']
    markers=[]
    for number,region in enumerate(regions,1):
        color=palette[(number-1)%len(palette)]
        summary=region_summary(directory,region)
        summaries.append({**summary,'adjustments':region['adjustments'],'mask_number':number,'mask_color':color})
        mask=load_mask(directory,region)
        overlay=Image.new('RGB',image.size,color)
        image=Image.composite(overlay,image,Image.fromarray((mask*65).astype(np.uint8)))
        ys,xs=np.where(mask>.5)
        if len(xs):
            index=np.argmin((xs-xs.mean())**2+(ys-ys.mean())**2)
            markers.append((int(xs[index]),int(ys[index]),str(number)))
    draw=ImageDraw.Draw(image)
    for x,y,label in markers:
        draw.rectangle((x-9,y-9,x+15,y+12),fill='#142019',outline='white')
        draw.text((x-4,y-6),label,fill='white')
    buf=io.BytesIO();image.save(buf,format='JPEG',quality=85)
    analysis=job.get('decision') or {}
    context={'style':state.style,'strength':state.strength,'mode':state.mode,'use_ai':state.use_ai,'include_local':state.include_local,
             'parameters':recipe['parameters'],'curves':recipe['curves'],'enabled_regions':summaries,
             'parameter_ranges':{k:RANGES[k] for k in recipe['parameters']},
             'local_ranges':LocalAdjustments.model_json_schema()['properties'],
             'analysis':{k:analysis[k] for k in ['scene','subject','lighting','mood','rationale'] if k in analysis},
             'recent_edits':[{k:e[k] for k in ['instruction','explanation','changes']} for e in job.get('refinement_history',[])[-5:]]}
    return context,buf.getvalue() if regions else None

def merge_refinement(job, state: RenderRequest, patch: Refinement):
    recipe=build_recipe(job['metrics'],job.get('decision'),state)
    if set(patch.parameters)-set(recipe['parameters']):
        raise ValueError('增量修改包含当前模式未启用的参数。')
    if state.mode=='style' and PHOTO_ONLY.intersection(patch.parameters):
        raise ValueError('通用风格不能修改照片专属参数。')
    validate_parameters({**recipe['parameters'],**patch.parameters})
    allowed={r['id']:r for r in selected_regions(job,state)}
    ids=[item.region_id for item in patch.local]
    if len(ids)!=len(set(ids)) or any(i not in allowed for i in ids):
        raise ValueError('增量修改引用了不存在、未启用或当前模式不允许的选区。')
    changes=[]
    result=copy.deepcopy(job)
    next_state=state.model_dump()
    for key,value in patch.parameters.items():
        # Match the final precision of the parameter engine.
        after=round(value,2) if key=='Exposure2012' else round(value)
        before=recipe['parameters'][key]
        if before==after:continue
        next_state['overrides'][key]=after
        changes.append({'scope':'global','parameter':key,'before':before,'after':after})
    for channel,points in patch.curves.items():
        after=[[p.x,p.y] for p in points]
        before=recipe['curves'][channel]
        if before==after:continue
        next_state['curve_overrides'][channel]=[p.model_dump() for p in points]
        changes.append({'scope':'curve','parameter':channel,'before':before,'after':after})
    by_id={r['id']:r for r in result.get('regions',[])}
    local_before={}
    for target in patch.local:
        region=by_id[target.region_id]
        merged={**region['adjustments'],**target.adjustments}
        LocalAdjustments.model_validate(merged)
        changed={k:v for k,v in target.adjustments.items() if region['adjustments'].get(k,0)!=v}
        if not changed:continue
        local_before[region['id']]={k:copy.deepcopy(region.get(k)) for k in ['adjustments','reason','adjustment_source','manual_adjustments']}
        for key,value in changed.items():
            changes.append({'scope':'local','region_id':region['id'],'region_name':region['name'],'parameter':key,'before':region['adjustments'].get(key,0),'after':value})
        region['adjustments']=merged
        region['reason']=target.reason
        region['adjustment_source']='AI 增量修改'
        # Preserve this user-requested edit during a later full re-analysis.
        region['manual_adjustments']=True
        region['revision']=region.get('revision',0)+1
    request=RenderRequest.model_validate(next_state)
    build_recipe(job['metrics'],job.get('decision'),request)
    result['edit_state']=request.model_dump()
    entry={'time':datetime.now(timezone.utc).isoformat(),'instruction':'','explanation':patch.explanation,
           'changes':changes,'before_state':state.model_dump(),'before_local':local_before}
    return result,entry

def undo_refinement(job):
    if not job.get('refinement_history'):
        raise ValueError('没有可撤销的 AI 修改。')
    result=copy.deepcopy(job)
    entry=result['refinement_history'][-1]
    regions={r['id']:r for r in result.get('regions',[])}
    if set(entry['before_local'])-set(regions):
        raise ValueError('上次修改的选区已被删除，无法撤销。')
    for region_id,values in entry['before_local'].items():
        region=regions[region_id]
        region.update(copy.deepcopy(values))
        region['revision']=region.get('revision',0)+1
    result['edit_state']=copy.deepcopy(entry['before_state'])
    result['refinement_history'].pop()
    return result
