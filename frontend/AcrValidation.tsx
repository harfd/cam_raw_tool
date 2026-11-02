import React,{useState,useEffect,useRef} from 'react';
import {json,post,request,downloadValidation} from './api';
import {usePreviewUrl} from './usePreviewUrl';

function canonical(value:any):string {
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
 return JSON.stringify(value);
}
export function AcrValidation({job,state,disabled,preview}:{job:any;state:any;disabled:boolean;preview:string}){
 const [snapshot,setSnapshot]=useState<any>(null),[pending,setPending]=useState(false),[error,setError]=useState('');
 const [report,setReport]=useState<any>(null),[assume,setAssume]=useState(false),[version,setVersion]=useState(''),[profile,setProfile]=useState('');
 const [before,setBefore]=usePreviewUrl(),[after,setAfter]=usePreviewUrl(),[heat,setHeat]=usePreviewUrl(),[detail,setDetail]=usePreviewUrl();
 const [position,setPosition]=useState({x:.5,y:.5}),[split,setSplit]=useState(50),[pixel,setPixel]=useState(false);
 const regionBasis=(job.regions||[]).map((r:any)=>Object.fromEntries(['id','enabled','revision','feather','adjustments'].map(k=>[k,r[k]??null])));
 const detailKey=canonical(state)+canonical(regionBasis)+canonical(position);
 const activeDetail=useRef(detailKey);activeDetail.current=detailKey;
 useEffect(()=>()=>{activeDetail.current='unmounted';},[]);
 const stale=snapshot&&(canonical(job.decision??null)!==canonical(snapshot.decision)||canonical(state)!==canonical(snapshot.state)||canonical(regionBasis)!==canonical(snapshot.regions));
 useEffect(()=>{let active=true;json(`/jobs/${job.id}/validation`).then(s=>{if(active){setSnapshot(s);setReport(s?.report||null);}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[job.id]);
 useEffect(()=>{
  if(!snapshot)return;const controller=new AbortController();
  const load=async(kind:string,set:(v:string)=>void)=>{const blob=await(await request(`/jobs/${job.id}/validation/${snapshot.id}/${kind}`,{signal:controller.signal})).blob();if(!controller.signal.aborted)set(URL.createObjectURL(blob));};
  load('reference',setBefore).catch(e=>{if(e.name!=='AbortError')setError(e.message);});
  if(report){load('acr',setAfter).catch(e=>{if(e.name!=='AbortError')setError(e.message);});load('difference',setHeat).catch(e=>{if(e.name!=='AbortError')setError(e.message);});}
  return()=>controller.abort();
 },[snapshot?.id,report]);
 useEffect(()=>{setDetail('');},[canonical(state),canonical(regionBasis)]);
 async function action(run:()=>Promise<void>){setPending(true);setError('');try{await run();}catch(e:any){setError(e.message);}finally{setPending(false);}}
 async function freeze(){await action(async()=>{const next=await json(`/jobs/${job.id}/validation`,post(state));setSnapshot(next);setReport(null);setAfter('');setHeat('');});}
 async function inspect(){const key=detailKey;await action(async()=>{const blob=await(await request(`/jobs/${job.id}/detail?x=${position.x}&y=${position.y}`,post(state))).blob();if(activeDetail.current===key)setDetail(URL.createObjectURL(blob));});}
 async function compare(file?:File){if(!file||!snapshot)return;await action(async()=>{const form=new FormData();form.append('image',file);const query=new URLSearchParams({assume_srgb:String(assume),acr_version:version,camera_profile:profile});setReport(await json(`/jobs/${job.id}/validation/${snapshot.id}/compare?${query}`,{method:'POST',body:form}));});}
 return <section className="acr-validation" aria-label="ACR 对照验证">
  <h2>高精度预览与 ACR 对照</h2>
  <p className="muted">预览从 16 位 sRGB 解码数据进行浮点处理。局部 100% 使用原尺寸解码，每个图像像素对应一个显示像素。首次查看需要生成缓存。</p>
  <details><summary>查看原尺寸局部（100%）</summary><p>点击下图选择位置，再点击“查看局部”。</p>
   {preview&&<img className="detail-picker" src={preview} alt="选择原尺寸查看位置" onClick={e=>{const r=e.currentTarget.getBoundingClientRect();setPosition({x:(e.clientX-r.left)/r.width,y:(e.clientY-r.top)/r.height});setDetail('');}}/>}
   <p>查看位置：{Math.round(position.x*100)}% / {Math.round(position.y*100)}%</p><button className="secondary" disabled={disabled||pending} onClick={inspect}>查看局部 100%</button>
   {detail&&<div className="pixel-scroll"><img src={detail} alt="原尺寸局部预览"/></div>}
   <p className="tiny muted">质感与颗粒可能随处理分辨率变化；这里用于检查细节，不代表 Adobe 的原尺寸渲染。</p>
  </details>
  <p>先应用曲线和局部调整草稿，再冻结方案。解压验证包，在 ACR 打开副本、载入同包 XMP，以 sRGB 原始画幅导出成片，然后在此导入。</p>
  <button className="secondary" disabled={disabled||pending} onClick={freeze}>{pending?'正在处理…':'冻结当前方案'}</button>
  {snapshot&&<><div className="validation-actions"><span>快照 {snapshot.id.slice(0,8)} · {snapshot.reference_size.join(' × ')}</span><button disabled={pending} onClick={()=>action(async()=>{await downloadValidation(job.id,snapshot.id,'package');})}>保存 ACR 验证包</button></div>
   {stale&&<p role="status" className="validation-warning">当前方案或选区已变化。下面对照的是冻结快照；需要验证新效果时请重新冻结。</p>}
   <label className="field-label">实际 ACR 版本<input aria-label="实际 ACR 版本" value={version} onChange={e=>setVersion(e.target.value)} maxLength={100}/></label>
   <label className="field-label">实际相机配置文件<input aria-label="实际相机配置文件" value={profile} onChange={e=>setProfile(e.target.value)} maxLength={200}/></label>
   <label className="checkbox"><input type="checkbox" checked={assume} onChange={e=>setAssume(e.target.checked)}/>无 ICC 时，我确认导入成片为 sRGB</label>
   <label className="field-label">导入此快照的 ACR 实际成片<input aria-label="ACR 实际成片" type="file" accept=".jpg,.jpeg,.png,.tif,.tiff" disabled={pending||disabled} onChange={e=>{compare(e.target.files?.[0]);e.target.value='';}}/></label>
   {report&&<><p>{report.color_basis}；比较尺寸 {report.comparison_size.join(' × ')}。实际版本：{report.acr_version||'未填写'}；配置文件：{report.camera_profile||'未填写'}。</p>
    <label className="checkbox"><input type="checkbox" checked={pixel} onChange={e=>setPixel(e.target.checked)}/>以参考图像 100% 查看（可滚动）</label>
    <div className={'validation-compare '+(pixel?'pixel-scroll':'')}><div className="compare" style={pixel?{width:snapshot.reference_size[0],maxWidth:'none'}:{}}>
      {after&&<img src={after} alt="ACR 实际成片对照"/>}<div className="before-layer" style={{clipPath:`inset(0 ${100-split}% 0 0)`}}>{before&&<img src={before} alt="冻结的本地预览"/>}</div>
      <span className="image-tag before-tag">本地快照</span><span className="image-tag after-tag">ACR 成片</span>
      <input aria-label="ACR 对照分界线" className="compare-range" type="range" min="0" max="100" value={split} onChange={e=>setSplit(+e.target.value)}/>
    </div></div>
    <table><thead><tr><th>区域</th><th>平均绝对差 /255</th><th>亮度偏差 /255</th><th>平均 ΔE76</th></tr></thead><tbody>{report.scopes.map((s:any)=><tr key={s.name}><td>{s.name}</td><td>{s.mae_255.toFixed(2)}</td><td>{s.luma_bias_255.toFixed(2)}</td><td>{s.delta_e76_mean.toFixed(2)}</td></tr>)}</tbody></table>
    <p>RGB 平均偏差：{report.rgb_bias_255.map((x:number)=>x.toFixed(2)).join(' / ')}；RMSE：{report.rmse_255.toFixed(2)}；ΔE76 P95：{report.delta_e76_p95.toFixed(2)}。</p>
    {heat&&<><img className="difference-image" src={heat} alt="ACR 与本地预览的色差图"/><p className="tiny muted">色差图：暗色接近 0，亮色为 ΔE76 ≥30。画幅、方向和图像内容须一致；相同比例不能证明像素对齐。</p></>}
    <p className="tiny muted">{report.limits}</p><button onClick={()=>action(async()=>{await downloadValidation(job.id,snapshot.id,'report');})}>保存对照报告</button>
   </>}
  </>}
  {error&&<p role="alert" className="form-error">{error}</p>}
 </section>;
}
