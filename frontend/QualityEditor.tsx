import {useState} from 'react';
import {ShieldCheck,LoaderCircle,Undo2} from 'lucide-react';

function stable(value:any):string{if(Array.isArray(value))return '['+value.map(stable).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stable(value[k])).join(',')+'}';return JSON.stringify(value);}
function percent(value:number){return (value*100).toFixed(2)+'%';}
export function QualityEditor({job,state,disabled,pending,autoCorrect,onAutoCorrect,onCheck,onCorrect,onUndo}:any){
 const [protect,setProtect]=useState(true);
 const basis={state,decision:job.decision??null,regions:(job.regions||[]).map((r:any)=>Object.fromEntries(['id','enabled','revision','feather','adjustments'].map(k=>[k,r[k]??null]))),preview_version:job.metrics?.preview_version??1};
 const report=job.quality_report;
 const fresh=!!report&&stable(basis)===stable(report.basis);
 const correction=fresh?report.correction:null;
 const automaticLast=job.refinement_history?.at(-1)?.kind==='auto_correction';
 return <section className="analysis-card quality-card"><div className="panel-heading"><h2><ShieldCheck size={16}/>效果检查与自动修正</h2><span className="pill">本地检查 · 无需 Key</span></div><p className="tiny muted">对照原始预览，检查调色后新增的亮部接近纯白、暗部接近纯黑、颜色饱和及过度提亮风险。原有暗调与高光不会仅因占比高而被判为问题。</p>
 <label className="checkbox"><input type="checkbox" checked={autoCorrect} disabled={disabled} onChange={e=>onAutoCorrect(e.target.checked)}/>AI 整图分析后自动修正</label><label className="checkbox"><input type="checkbox" checked={protect} disabled={disabled} onChange={e=>setProtect(e.target.checked)}/>保留手动参数数值及手动局部调整</label>
 <div className="quality-actions"><button className="secondary" disabled={disabled} onClick={onCheck}>{pending?<LoaderCircle className="spin" size={15}/>:<ShieldCheck size={15}/>}检查当前效果</button><button className="secondary" disabled={disabled} onClick={()=>onCorrect(protect)}>检查并自动修正</button>{automaticLast&&<button className="text-button" disabled={disabled} onClick={onUndo}><Undo2 size={13}/>撤销自动修正</button>}</div>
 {job.quality_error&&<p className="quality-warning">{job.quality_error}</p>}
 {!report&&<p className="acr-hint">尚未检查。整图 AI 分析和自然语言修改完成后会自动检查；自然语言修改后保留用户指令，不自动改写结果。</p>}
 {report&&!fresh&&<p className="quality-warning" role="status">参数或选区已变化，检查结果已过期，请重新检查。</p>}
 {fresh&&<div className="quality-result" role="status"><strong>{report.issues.length?'检测到 '+report.issues.length+' 项预览风险':'未检测到明显新增风险'}</strong>{report.issues.length>0&&<ul>{report.issues.map((issue:any,i:number)=><li key={i}>{issue.scope} · {issue.label}<span>{percent(issue.fraction)}（提示阈值 {percent(issue.threshold)}）</span></li>)}</ul>}<div className="quality-metrics">{report.scopes.map((scope:any)=><div key={scope.region_id||'global'}><b>{scope.name}</b><span>新增近白 {percent(scope.metrics.new_highlights)}</span><span>新增近黑 {percent(scope.metrics.new_blacks)}</span><span>新增高饱和 {percent(scope.metrics.new_saturation)}</span><span>较大提亮 {percent(scope.metrics.over_lift)}</span></div>)}</div>{correction&&<p className="quality-summary">{correction.reason} 共接受 {correction.iterations} 步，试算 {correction.evaluations} 个状态。{correction.changed&&'可在修改记录查看前后数值并撤销。'}</p>}{correction?.changed&&<div className="quality-before-after">{correction.before_scopes.map((before:any,i:number)=><p key={before.region_id||'global'}>{before.name}：新增近白 {percent(before.metrics.new_highlights)} → {percent(report.scopes[i].metrics.new_highlights)}；新增近黑 {percent(before.metrics.new_blacks)} → {percent(report.scopes[i].metrics.new_blacks)}；新增高饱和 {percent(before.metrics.new_saturation)} → {percent(report.scopes[i].metrics.new_saturation)}；较大提亮 {percent(before.metrics.over_lift)} → {percent(report.scopes[i].metrics.over_lift)}</p>)}</div>}</div>}
 <p className="acr-hint">自动修正最多接受 4 步、试算 33 个状态；曝光累计不超过 0.3 EV，滑块和 RGB 总曲线也有幅度限制。保留色相、校准、通道曲线与蒙版范围。预览检测不代表 RAW 细节可恢复，最终以 Camera Raw 为准。</p></section>;
}
