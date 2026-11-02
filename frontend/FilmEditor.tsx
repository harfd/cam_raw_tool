import {useEffect,useState,useRef} from 'react';
import {Film,LoaderCircle} from 'lucide-react';
import {json,post,request,native,downloadFilm} from './api';
import {usePreviewUrl} from './usePreviewUrl';

const initial={film:'kodak_portra_400',paper:'kodak_portra_endura',exposure:0,print_exposure:0,auto_exposure:true,grain:true,halation:1,include_local_exposure:false,format:'preview'};
export function FilmEditor({jobId,disabled,regions=[]}:{jobId:string;disabled:boolean;regions?:any[]}){
 const [catalog,setCatalog]=useState<any>(null),[options,setOptions]=useState(initial),[task,setTask]=useState<any>({status:'loading'});
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[submitting,setSubmitting]=useState(false),[saving,setSaving]=useState(false);
 const [after,setAfter]=usePreviewUrl(),[before,setBefore]=usePreviewUrl();const [split,setSplit]=useState(50);const [previewError,setPreviewError]=useState(''),[previewRetry,setPreviewRetry]=useState(0);
 const loaded=useRef({operation:'',retry:0});
 const running=submitting||['queued','running'].includes(task.status);
 const shown=task.status==='complete'?task:task.previous;
 const positive=catalog?.films?.find((f:any)=>f.id===options.film)?.type==='positive';
 useEffect(()=>{const c=new AbortController();Promise.all([json('/film/catalog',{signal:c.signal}),json(`/jobs/${jobId}/film`,{signal:c.signal})]).then(([conf,t])=>{if(c.signal.aborted)return;setCatalog(conf);setTask(t);if(t.options)setOptions(t.options);}).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[jobId]);
 useEffect(()=>{if(!['queued','running'].includes(task.status))return;let active=true;const timer=setInterval(()=>{json(`/jobs/${jobId}/film`).then(t=>{if(active)setTask(t);}).catch(e=>{if(active)setError(e.message);});},1000);return()=>{active=false;clearInterval(timer);};},[jobId,task.status]);
 useEffect(()=>{if(!shown||(loaded.current.operation===shown.operation&&loaded.current.retry===previewRetry))return;const c=new AbortController();Promise.all(['preview','before'].map(async k=>await(await request(`/jobs/${jobId}/film/${shown.operation}/${k}`,{signal:c.signal})).blob())).then(([a,b])=>{if(!c.signal.aborted){setAfter(URL.createObjectURL(a));setBefore(URL.createObjectURL(b));setPreviewError('');loaded.current={operation:shown.operation,retry:previewRetry};}}).catch(e=>{if(e.name!=='AbortError')setPreviewError(e.message);});return()=>c.abort();},[jobId,shown?.operation,previewRetry]);
 const localSnapshot=regions.filter(r=>r.enabled&&r.adjustments?.exposure).map(r=>({id:r.id,revision:r.revision??0,feather:r.feather??0,exposure:r.adjustments.exposure}));
 const changed=shown?.options&&(Object.keys(initial).filter(k=>k!=='format').some(k=>(options as any)[k]!==shown.options[k])||(options.include_local_exposure&&JSON.stringify(localSnapshot)!==JSON.stringify(shown.local_snapshot||[])));
 function change(key:string,value:any){setOptions(o=>({...o,[key]:value,...(key==='film'&&catalog?.films.find((f:any)=>f.id===value)?.type==='positive'?{print_exposure:0}:{})}));setNotice('');}
 async function run(format:string){setSubmitting(true);setError('');setNotice('');try{setTask(await json(`/jobs/${jobId}/film/render`,post({...options,format})));}catch(e:any){setError(e.message);}finally{setSubmitting(false);}}
 async function cancel(){try{await json(`/jobs/${jobId}/film/cancel`,post({}));}catch(e:any){setError(e.message);}}
 async function save(){setSaving(true);setError('');try{const blob=native?undefined:await(await request(`/jobs/${jobId}/film/${shown.operation}/download`)).blob();if(await downloadFilm(jobId,shown.operation,shown.result.filename,blob))setNotice('胶片成片已保存。');}catch(e:any){setError(e.message);}finally{setSaving(false);}}
 return <section className="film-editor" aria-label="胶片模拟">
  <div className="panel-heading"><h2><Film size={16}/>胶片模拟</h2><span>spektrafilm</span></div>
  <p className="film-intro">从 NEF 原片独立处理，保留拍摄白平衡。上方 Camera Raw 调色不叠加到此处；胶片效果保存为成片，不包含在 XMP 中。</p>
  {(error||task.error)&&<p role="alert" className="form-error">{error||task.error}</p>}{notice&&<p role="status" className="accent">{notice}</p>}
  {previewError&&<p className="form-error">胶片预览加载失败：{previewError}<button className="text-button" onClick={()=>setPreviewRetry(n=>n+1)}>重试胶片预览</button></p>}
  {!catalog?<p className="muted">正在检查胶片引擎…</p>:!catalog.available?<p className="quality-warning">{catalog.message}</p>:<>
   <fieldset className="film-controls" disabled={disabled||running||task.status==='loading'}>
    {(['film','paper'] as const).map((key,i)=><label key={key}>{['胶片','相纸'][i]}<select className="acr-select" disabled={key==='paper'&&positive} aria-label={['胶片型号','相纸型号'][i]} value={options[key]} onChange={e=>change(key,e.target.value)}>{catalog[i?'papers':'films'].map((f:any)=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label>)}
    {([['exposure','胶片曝光',-4,4],['print_exposure','冲印曝光',-3,3],['halation','高光晕染',0,2]] as const).map(([key,label,min,max])=><label key={key}>{label} <b>{options[key].toFixed(1)}{key!=='halation'?' EV':''}</b><input disabled={key==='print_exposure'&&positive} aria-label={label} type="range" min={min} max={max} step={.1} value={options[key]} onChange={e=>change(key,+e.target.value)}/></label>)}
    <div className="film-checkboxes">{([['grain','胶片颗粒'],['auto_exposure','自动曝光'],['include_local_exposure','沿用已启用选区的局部曝光']] as const).map(([key,label])=><label className="checkbox" key={key}><input type="checkbox" checked={options[key]} onChange={e=>change(key,e.target.checked)}/>{label}</label>)}</div>
   </fieldset>
   {positive&&<p className="tiny muted">反转片直接扫描，不使用相纸和冲印曝光。</p>}
   <p className="tiny muted">局部曝光取自已保存选区，其他局部滑块不应用。缩图预览的颗粒及光晕与全尺寸成片可能不同。</p>
   <div className="film-actions">{[['preview','生成胶片预览'],['tiff','渲染 16 位 TIFF'],['jpeg','渲染 JPEG']].map(([format,label])=><button className="secondary" key={format} disabled={disabled||running} onClick={()=>run(format)}>{label}</button>)}{running&&<button className="text-button" onClick={cancel}>取消渲染</button>}</div>
   {running&&<p role="status" className="film-progress"><LoaderCircle className="spin" size={14}/>{task.stage||'正在提交'} · 首次启动和全尺寸渲染可能需要数分钟</p>}
   {running&&after&&<p className="tiny muted">渲染期间显示上一次完成的胶片结果。</p>}
   {['cancelled','interrupted','failed'].includes(task.status)&&<p className="quality-warning">{task.stage}，可以调整参数后重试。</p>}
   {changed&&<p className="quality-warning">参数已变化，请重新生成。下面显示上一次完成的结果。</p>}
   {after&&before&&<div className="preview-canvas film-preview"><div className="compare"><img src={after} alt="胶片模拟结果"/><div className="before-layer" style={{clipPath:`inset(0 ${100-split}% 0 0)`}}><img src={before} alt="胶片处理前"/></div><div className="split-line" style={{left:split+'%'}}/><span className="image-tag before-tag">处理前</span><span className="image-tag after-tag">胶片结果</span><input className="compare-range" type="range" aria-label="胶片前后对比" min={0} max={100} value={split} onChange={e=>setSplit(+e.target.value)}/></div></div>}
   {shown&&<div className="film-result"><span>{shown.result.width} × {shown.result.height} · {shown.result.bit_depth} 位 · {shown.elapsed_seconds} 秒{shown.options.format==='preview'?' · 缩图预览':''}</span>{shown.options.format!=='preview'&&<button className="primary" disabled={saving} onClick={save}>{saving?'正在保存…':changed||task.status!=='complete'?'保存上次结果':'保存成片'}</button>}</div>}
   <details className="film-credits"><summary>胶片引擎与授权</summary><p>Film modeling powered by spektrafilm, by Andrea Volpato. 模拟代码采用 GPLv3；胶片配置采用 CC BY-SA 4.0。照片成片归你所有。本软件按 GPLv3 提供，不作担保；允许按许可再分发。对应源码和许可证随软件提供。</p><p>https://github.com/andreavolpato/spektrafilm</p></details>
  </>}
 </section>;
}
