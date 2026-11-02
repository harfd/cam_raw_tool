import { useEffect, useRef, useState } from 'react';
import { json, post, request } from './api';
import { LoaderCircle, Paintbrush, Scan, Undo2 } from 'lucide-react';

export type Region = { id:string; name:string; kind:string; enabled:boolean; revision:number; area:number; feather:number; source:string; reason?:string; adjustments:Record<string,number>; adjustment_source?:string };
const controls = [['exposure','曝光',-2,2,.05],['highlights','高光',-100,50,1],['shadows','阴影',-60,60,1],['whites','白色色阶',-60,60,1],['blacks','黑色色阶',-60,60,1],['contrast','对比度',-60,60,1],['temperature','冷暖',-60,60,1],['tint','色调',-40,40,1],['saturation','饱和度',-60,60,1],['blue','蓝色曲线',0,40,1],['clarity','清晰度',-40,40,1],['texture','纹理',-40,40,1],['dehaze','去雾',-30,40,1]] as const;

export function LocalEditor({job, original, processed, onChange, onError, disabled}:any) {
 const regions:Region[]=job.regions || [];
 const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[tool,setTool]=useState<'add'|'erase'|'box'>('add');
 const [adjusted,setAdjusted]=useState(true);
 const displayed=adjusted&&processed?processed:original;
 const [radius,setRadius]=useState(.015),[overlay,setOverlay]=useState(true),[adjustments,setAdjustments]=useState<Record<string,number>>({});
 const [previewError,setPreviewError]=useState(''),[previewReady,setPreviewReady]=useState(false),[retry,setRetry]=useState(0);
 const canvas=useRef<HTMLCanvasElement>(null),base=useRef<HTMLCanvasElement|null>(null);
 const gesture=useRef<{points:[number,number][];start:[number,number]}|null>(null);
 const region=regions.find(r=>r.id===selected);
 useEffect(()=>{ if(!regions.some(r=>r.id===selected))setSelected(regions[0]?.id||''); },[regions,selected]);
 const adjustmentKey=JSON.stringify(region?.adjustments);
 useEffect(()=>{setAdjustments(region?.adjustments || {});},[selected,region?.revision,adjustmentKey]);
 useEffect(()=>{
  if(!displayed||!canvas.current)return;
  const controller=new AbortController();
  let canceled=false;
  setPreviewReady(false);setPreviewError('');
  (async()=>{
   const image=await new Promise<HTMLImageElement>((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>reject(new Error('照片效果预览加载失败，请重试选区预览。'));i.src=displayed;});
   if(canceled)return;
   const back=document.createElement('canvas');back.width=image.naturalWidth;back.height=image.naturalHeight;
   const ctx=back.getContext('2d')!;ctx.drawImage(image,0,0);
   if(region&&overlay){
    const blob=await(await request(`/jobs/${job.id}/regions/${region.id}/mask`,{signal:controller.signal})).blob();
    const bitmap=await createImageBitmap(blob).catch(()=>{throw new Error('选区图像解码失败，请重试选区预览。');});
    if(canceled){bitmap.close();return;}
    const temp=document.createElement('canvas');temp.width=back.width;temp.height=back.height;
    const t=temp.getContext('2d')!;t.drawImage(bitmap,0,0);bitmap.close();
    const pixels=t.getImageData(0,0,temp.width,temp.height);
    for(let i=0;i<pixels.data.length;i+=4){const alpha=pixels.data[i];pixels.data[i]=210;pixels.data[i+1]=95;pixels.data[i+2]=95;pixels.data[i+3]=Math.round(alpha*.45);}
    t.putImageData(pixels,0,0);ctx.drawImage(temp,0,0);
   }
   if(canceled||!canvas.current)return;
   base.current=back;canvas.current.width=back.width;canvas.current.height=back.height;
   canvas.current.getContext('2d')!.drawImage(back,0,0);
   setPreviewReady(true);
  })().catch(e=>{if(!canceled&&e.name!=='AbortError')setPreviewError(e.message||'选区预览加载失败，请重试。');});
  return()=>{canceled=true;controller.abort();};
 },[displayed,job.id,selected,region?.revision,overlay,retry]);
 async function run(operation:()=>Promise<any>){setBusy(true);try{const next=await operation();onChange(next);return next;}catch(e:any){onError(e.message);}finally{setBusy(false);}}
 function update(body:any){if(region)return run(()=>json(`/jobs/${job.id}/regions/${region.id}`,{...post(body),method:'PUT'}));}
 function point(e:React.PointerEvent<HTMLCanvasElement>):[number,number]{const b=e.currentTarget.getBoundingClientRect();return[Math.max(0,Math.min(1,(e.clientX-b.left)/b.width)),Math.max(0,Math.min(1,(e.clientY-b.top)/b.height))];}
 function down(e:React.PointerEvent<HTMLCanvasElement>){
  if(busy||disabled||!previewReady||(tool!=='box'&&!region))return;
  e.currentTarget.setPointerCapture(e.pointerId);const p=point(e);gesture.current={points:[p],start:p};
 }
 function move(e:React.PointerEvent<HTMLCanvasElement>){
  const g=gesture.current,c=canvas.current;if(!g||!c)return;const p=point(e);g.points.push(p);
  const ctx=c.getContext('2d')!;
  if(tool==='box'){
   if(base.current)ctx.drawImage(base.current,0,0);
   ctx.strokeStyle='#c5e4cc';ctx.lineWidth=3;ctx.strokeRect(g.start[0]*c.width,g.start[1]*c.height,(p[0]-g.start[0])*c.width,(p[1]-g.start[1])*c.height);
  }else{
   const prev=g.points[g.points.length-2];ctx.strokeStyle=tool==='erase'?'rgba(80,160,220,.6)':'rgba(230,90,90,.6)';
   ctx.lineCap='round';ctx.lineJoin='round';ctx.lineWidth=radius*Math.max(c.width,c.height)*2;
   ctx.beginPath();ctx.moveTo(prev[0]*c.width,prev[1]*c.height);ctx.lineTo(p[0]*c.width,p[1]*c.height);ctx.stroke();
  }
 }
 async function up(e:React.PointerEvent<HTMLCanvasElement>){
  const g=gesture.current;gesture.current=null;if(!g)return;const p=point(e);g.points.push(p);
  if(tool==='box'){
   const bbox=[Math.min(g.start[0],p[0]),Math.min(g.start[1],p[1]),Math.max(g.start[0],p[0]),Math.max(g.start[1],p[1])];
   const next=await run(()=>json(`/jobs/${job.id}/regions`,post({name:'框选主体',bbox})));
   if(next){setSelected(next.regions[next.regions.length-1].id);setTool('add');}
  }else if(region){
   const points=g.points.length>4000?g.points.filter((_,i)=>i%Math.ceil(g.points.length/3999)===0):g.points;
   await run(()=>json(`/jobs/${job.id}/regions/${region.id}/paint`,post({points,radius,erase:tool==='erase'})));
  }
 }
 return <section className="local-editor analysis-card">
  <div className="panel-heading"><h2><Paintbrush size={16}/>局部选区与调整</h2><span>本机分割 · 可修正边界</span></div>
  <div className="local-actions"><button className="secondary" disabled={busy||disabled} onClick={()=>run(()=>json(`/jobs/${job.id}/segment`,post({})))}>{busy?<LoaderCircle className="spin" size={15}/>:<Scan size={15}/>}识别本地选区</button><button className="secondary" disabled={busy||disabled} onClick={async()=>{const next=await run(()=>json(`/jobs/${job.id}/regions`,post({name:'手绘选区'})));if(next)setSelected(next.regions[next.regions.length-1].id);}}>新建手绘</button><label className="checkbox"><input type="checkbox" checked={overlay} onChange={e=>setOverlay(e.target.checked)}/>显示选区</label><label className="checkbox"><input type="checkbox" checked={adjusted} onChange={e=>setAdjusted(e.target.checked)}/>显示调整效果</label></div>
  <p className="tiny muted">自动识别人像、天空、植被、水面和地面；框选支持其他主体。红色为当前选区，可用画笔添加或擦除。AI 分析会自动识别并为实际选区制定调整。</p>
  <div className="region-tabs">{regions.map(r=><button key={r.id} className={selected===r.id?'chosen':''} onClick={()=>setSelected(r.id)}>{r.enabled?'●':'○'} {r.name}<small>{(r.area*100).toFixed(1)}%</small></button>)}</div>
  <div className="local-toolbar">{[['add','添加画笔'],['erase','擦除画笔'],['box','框选主体']].map(([id,title])=><button key={id} className={tool===id?'chosen':''} disabled={busy||disabled} onClick={()=>setTool(id as any)}>{title}</button>)}<label>笔刷大小 <input aria-label="局部笔刷大小" type="range" min=".003" max=".08" step=".001" value={radius} onChange={e=>setRadius(+e.target.value)}/></label>{region&&<button disabled={busy||disabled} onClick={()=>run(()=>json(`/jobs/${job.id}/regions/${region.id}/undo`,post({})))}><Undo2 size={13}/>撤销笔画</button>}{region&&<button disabled={busy||disabled} onClick={()=>run(()=>json(`/jobs/${job.id}/regions/${region.id}/refine`,post({})))}>细化边缘</button>}</div>
  {previewError&&<div className="alert" role="alert">{previewError}<button className="secondary" onClick={()=>setRetry(n=>n+1)}>重试选区预览</button></div>}
  <canvas ref={canvas} aria-label="局部选区编辑画布" aria-busy={!previewReady} className="mask-canvas" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={()=>{gesture.current=null;}}/>
  {region&&<><div className="region-heading"><div><b>{region.name}</b><small>{region.source}</small></div><label className="checkbox"><input aria-label="启用当前局部调整" type="checkbox" disabled={busy||disabled} checked={region.enabled} onChange={e=>update({enabled:e.target.checked})}/>启用调整</label><button className="text-button" disabled={busy||disabled} onClick={()=>run(()=>json(`/jobs/${job.id}/regions/${region.id}`,{method:'DELETE'}))}>删除选区</button></div>{region.reason&&<p className="rationale">{region.reason}</p>}
   <div className="local-sliders">{controls.map(([key,label,min,max,step])=><div key={key}><div><label htmlFor={'local-'+key}>{label}</label><output>{adjustments[key]||0}</output></div><input id={'local-'+key} type="range" disabled={busy||disabled} min={min} max={max} step={step} value={adjustments[key]||0} onChange={e=>setAdjustments({...adjustments,[key]:+e.target.value})}/></div>)}</div>
   <div className="local-footer"><label>边缘柔化 <input aria-label="选区边缘柔化" type="range" min="0" max="12" step="1" value={region.feather} disabled={busy||disabled} onChange={e=>update({feather:+e.target.value})}/></label><button className="secondary" disabled={busy||disabled} onClick={()=>update({adjustments})}>应用局部调整</button></div>
   <p className="tiny muted">{region.adjustment_source||'尚未设置局部参数'}。局部参数独立于全局风格强度；导出照片专属 XMP 时携带固定坐标笔刷选区。</p>
  </>}
 </section>;
}
