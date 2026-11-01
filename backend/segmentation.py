"""Offline semantic segmentation and persistent, editable image-space masks."""
import json
import threading
from pathlib import Path
from uuid import uuid4
import cv2
import numpy as np
from PIL import Image
from .models import LocalAdjustments

ASSETS=Path(__file__).parent/'assets'/'segformer'
_session=None
_inference_lock=threading.RLock()
REGION_CLASSES={
 'subject':('人物',[12]), 'sky':('天空',[2]),
 'vegetation':('植被',[4,9,17,66,72]), 'water':('水面',[21,26,60,128]),
 'ground':('地面',[3,6,11,13,46,52,91,94]),
}

def session():
 global _session
 if _session is None:
  import onnxruntime as ort
  if not (ASSETS/'model.onnx').exists():
   raise ValueError('本地分割模型缺失，请运行 scripts/download-model.py。')
  options=ort.SessionOptions();options.intra_op_num_threads=4
  _session=ort.InferenceSession(str(ASSETS/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
 return _session

def predict_probabilities(image):
 config=json.loads((ASSETS/'preprocessor_config.json').read_text())
 arr=np.asarray(image.resize((512,512),Image.Resampling.BILINEAR),dtype=np.float32)/255
 arr=(arr-np.array(config['image_mean'],np.float32))/np.array(config['image_std'],np.float32)
 tensor=np.transpose(arr,(2,0,1))[None].copy()
 with _inference_lock:
  model=session()
  logits=model.run(None,{model.get_inputs()[0].name:tensor})[0][0]
 logits-=logits.max(axis=0,keepdims=True)
 probs=np.exp(logits);probs/=probs.sum(axis=0,keepdims=True)
 return probs

def infer(image_path):
 image=Image.open(image_path).convert('RGB')
 return image,predict_probabilities(image)

def largest_component(mask):
 count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8))
 if count<=1: return mask.astype(np.uint8)
 return np.where(labels==1+np.argmax(stats[1:,cv2.CC_STAT_AREA]),255,0).astype(np.uint8)

def refine_person(image, coarse):
 """Re-detect at subject scale, then align the selection to RGB edges."""
 ys,xs=np.where(coarse>127)
 if not len(xs): return coarse
 margin=max(24,round(max(xs.max()-xs.min(),ys.max()-ys.min())*.15))
 box=(max(0,int(xs.min())-margin),max(0,int(ys.min())-margin),
      min(image.width,int(xs.max())+margin+1),min(image.height,int(ys.max())+margin+1))
 crop=image.crop(box)
 probabilities=predict_probabilities(crop)
 person=cv2.resize(probabilities[12],crop.size,interpolation=cv2.INTER_LINEAR)
 seeds=np.where(person>.4,cv2.GC_PR_FGD,cv2.GC_PR_BGD).astype(np.uint8)
 seeds[person<.03]=cv2.GC_BGD
 seeds[person>.97]=cv2.GC_FGD
 if np.any(seeds==cv2.GC_FGD) and np.any(seeds==cv2.GC_BGD):
  try:
   cv2.grabCut(np.asarray(crop),seeds,None,np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),3,cv2.GC_INIT_WITH_MASK)
   selected=(seeds==cv2.GC_FGD)|(seeds==cv2.GC_PR_FGD)
  except cv2.error:
   selected=person>.48
 else:
  selected=person>.48
 selected=largest_component(selected.astype(np.uint8)*255)
 output=np.zeros((image.height,image.width),np.uint8)
 output[box[1]:box[3],box[0]:box[2]]=selected
 # Reject unstable refinement rather than silently losing the entire subject.
 ratio=np.count_nonzero(output)/max(np.count_nonzero(coarse),1)
 return output if .25<ratio<2 else coarse

def new_region(directory,mask,name,kind,source):
 region_id=uuid4().hex
 Image.fromarray(mask.astype(np.uint8)).save(directory/f'{region_id}.png')
 return {'id':region_id,'name':name,'kind':kind,'source':source,'enabled':True,
         'feather':1.,'revision':0,'manual_adjustments':False,
         'adjustments':LocalAdjustments().model_dump(),'area':float(np.mean(mask>127))}

def segment(directory):
 image,probs=infer(directory/'original.jpg')
 regions=[];subject=None;sky=None
 for kind,(name,ids) in REGION_CLASSES.items():
  confidence=probs[ids].sum(axis=0)
  confidence=cv2.resize(confidence,image.size,interpolation=cv2.INTER_LINEAR)
  mask=(confidence>=.48).astype(np.uint8)*255
  if np.mean(mask>0)<.0008: continue
  # Keep only the largest person component, avoiding distant incidental people.
  if kind=='subject':
   mask=refine_person(image,largest_component(mask))
   subject=mask
  if kind=='sky': sky=mask
  regions.append(new_region(directory,mask,name,kind,'语义分割 + 局部重识别与边界修正' if kind=='subject' else 'SegFormer 本地语义分割'))
 if subject is not None:
  background=255-subject
  if sky is not None: background=np.minimum(background,255-sky)
  regions.append(new_region(directory,background,'主体外背景','background','人物及天空选区的补集'))
 return regions

def load_mask(directory,region,feather=True):
 mask=np.asarray(Image.open(directory/f"{region['id']}.png").convert('L'),dtype=np.float32)/255
 if feather and region.get('feather',0)>0:
  mask=cv2.GaussianBlur(mask,(0,0),region['feather'])
 return np.clip(mask,0,1)

def region_summary(directory,region):
 image=np.asarray(Image.open(directory/'original.jpg').convert('RGB'),dtype=np.float32)/255
 mask=load_mask(directory,region,False)>.5
 points=np.argwhere(mask)
 box=None
 if len(points):
  h,w=mask.shape
  box=[float(points[:,1].min()/w),float(points[:,0].min()/h),float((points[:,1].max()+1)/w),float((points[:,0].max()+1)/h)]
 return {'id':region['id'],'name':region['name'],'kind':region['kind'],
         'area':float(mask.mean()),'bbox':box,'mean_display_brightness':float(image[mask].mean()) if mask.any() else 0}

def create_custom(directory,name,bbox):
 image=np.asarray(Image.open(directory/'original.jpg').convert('RGB'))
 h,w=image.shape[:2];mask=np.zeros((h,w),np.uint8)
 source='手绘选区'
 if bbox is not None:
  if not all(np.isfinite(v) and 0<=v<=1 for v in bbox): raise ValueError('框选坐标超出图像。')
  x0,y0,x1,y1=bbox
  if x1-x0<.01 or y1-y0<.01: raise ValueError('框选区域过小。')
  left,top=max(1,int(x0*w)),max(1,int(y0*h))
  right,bottom=min(w-1,int(x1*w)),min(h-1,int(y1*h))
  if right<=left or bottom<=top: raise ValueError('框选区域无效。')
  # GrabCut is deterministic here and refines arbitrary user-specified subjects.
  bg=np.zeros((1,65),np.float64);fg=np.zeros((1,65),np.float64)
  try:
   cv2.grabCut(image,mask,(left,top,right-left,bottom-top),bg,fg,3,cv2.GC_INIT_WITH_RECT)
  except cv2.error:
   raise ValueError('框选区域无法分离前景，请扩大框选范围或使用手绘选区。') from None
  mask=np.where((mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD),255,0).astype(np.uint8)
  source='框选 + GrabCut 边界修正'
 return new_region(directory,mask,name,'custom',source)

def paint(directory,region,stroke):
 path=directory/f"{region['id']}.png"
 mask=np.asarray(Image.open(path).convert('L')).copy()
 Image.fromarray(mask).save(directory/f"{region['id']}.previous.png")
 h,w=mask.shape;radius=max(1,round(stroke.radius*max(h,w)))
 points=[(round(x*(w-1)),round(y*(h-1))) for x,y in stroke.points]
 value=0 if stroke.erase else 255
 for a,b in zip(points,points[1:]): cv2.line(mask,a,b,value,2*radius,cv2.LINE_8)
 for pt in [points[0],points[-1]]: cv2.circle(mask,pt,radius,value,-1)
 Image.fromarray(mask).save(path)
 region.update(revision=region.get('revision',0)+1,area=float(np.mean(mask>127)))

def refine_region(directory,region):
 path=directory/f"{region['id']}.png"
 old=np.asarray(Image.open(path).convert('L'))
 Image.fromarray(old).save(directory/f"{region['id']}.previous.png")
 image=Image.open(directory/'original.jpg').convert('RGB')
 if region['kind']=='subject':
  mask=refine_person(image,old)
 else:
  inside=old>127
  kernel=np.ones((7,7),np.uint8)
  fg=cv2.erode(inside.astype(np.uint8),kernel)>0
  bg=cv2.dilate(inside.astype(np.uint8),kernel)==0
  seeds=np.where(inside,cv2.GC_PR_FGD,cv2.GC_PR_BGD).astype(np.uint8)
  seeds[fg]=cv2.GC_FGD;seeds[bg]=cv2.GC_BGD
  if not fg.any() or not bg.any(): raise ValueError('选区过小或覆盖全图，请先用画笔调整。')
  try:
   cv2.grabCut(np.asarray(image),seeds,None,np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),2,cv2.GC_INIT_WITH_MASK)
  except cv2.error:
   raise ValueError('边界细化失败，请继续使用画笔修正。') from None
  mask=np.where((seeds==cv2.GC_FGD)|(seeds==cv2.GC_PR_FGD),255,0).astype(np.uint8)
 Image.fromarray(mask).save(path)
 region.update(revision=region.get('revision',0)+1,area=float(np.mean(mask>127)),source='本地选区边界细化')

def apply_plan(job):
 """Apply exact region IDs only. User-adjusted values survive re-analysis."""
 targets=((job.get('decision') or {}).get('editing_plan') or {}).get('local',[])
 regions={r['id']:r for r in job.get('regions',[])}
 for target in targets:
  region=regions.get(target['region_id'])
  if region is None: raise ValueError('AI 返回了不存在的区域 ID。')
  if not region.get('manual_adjustments'):
   region['adjustments']=LocalAdjustments.model_validate(target['adjustments']).model_dump()
   region['reason']=target['reason']
   region['adjustment_source']='AI 局部决策'

def selected_regions(job,request):
 if request.mode!='photo' or not request.include_local: return []
 return [r for r in job.get('regions',[]) if r['enabled']]
