import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowDownToLine, ArrowLeftRight, Check, ChevronRight, ImagePlus, LoaderCircle, Settings2, Sparkles, Trash2, X, Layers3, SlidersHorizontal, FolderOpen } from 'lucide-react';
import { download, json, post, request } from './api';
import './style.css';
import { LocalEditor, type Region } from './LocalEditor';
import { CameraRawPanels, type Curves, type CurveOverrides, type WhiteBalance } from './CameraRawPanels';
import { RefinementEditor } from './RefinementEditor';
import { QualityEditor } from './QualityEditor';
import { usePreviewUrl } from './usePreviewUrl';
import { AcrValidation } from './AcrValidation';
import { FilmEditor } from './FilmEditor';
import appIcon from '../src-tauri/icons/source.svg';

type Style = 'natural' | 'cinematic' | 'film';
type Job = { id: string; filename: string; status: string; created_at: string; error?: string; edit_state?: any; refinement_history?: any[]; quality_report?: any; quality_error?: string; metadata?: Record<string, string | number>; metrics?: any; regions?:Region[]; decision?: any; ai_model?: string; warnings?: string[]; template: { version: string; process_version: string; kind: string } };
const styles: {id: Style; name: string; description: string; color: string}[] = [
  { id: 'natural', name: '自然通透', description: '保留本色 · 轻盈层次', color: '#9dcbb2' },
  { id: 'cinematic', name: '电影感', description: '冷暖对比 · 克制色彩', color: '#c4b090' },
  { id: 'film', name: '复古胶片', description: '柔和反差 · 细腻颗粒', color: '#ac9ebc' },
];
const statusNames: Record<string, string> = { queued: '等待解码', decoding: '正在解码', ready: '本地分析完成', analyzing: 'AI 分析中', refining:'AI 修改中', correcting:'效果检查与修正中', complete: 'AI 分析完成', failed: '解码失败' };

function App() {
  const [jobs, setJobs] = useState<Job[]>([]), [job, setJob] = useState<Job | null>(null);
  const [settings, setSettings] = useState<any>(null), [showSettings, setShowSettings] = useState(false);
  const [style, setStyle] = useState<Style>('natural'), [strength, setStrength] = useState(.7), [mode, setMode] = useState('photo');
  const [params, setParams] = useState<Record<string, number>>({}), [overrides, setOverrides] = useState<Record<string, number>>({});
  const [whiteBalance,setWhiteBalance]=useState<WhiteBalance|null>(null),[whiteBalanceResult,setWhiteBalanceResult]=useState<any>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [original,setOriginal]=usePreviewUrl(),[processed,setProcessed]=usePreviewUrl();
  const [split, setSplit] = useState(50), [intent, setIntent] = useState(''), [name, setName] = useState('AI 自然通透');
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [uploading, setUploading] = useState(false), [rendering, setRendering] = useState(false), [exporting, setExporting] = useState(false);
  const [importOpen, setImportOpen] = useState(false), [raw, setRaw] = useState<File | null>(null), [xmp, setXmp] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [curves,setCurves] = useState<Curves>({rgb:[[0,0],[255,255]],red:[[0,0],[255,255]],green:[[0,0],[255,255]],blue:[[0,0],[255,255]]}), [curveOverrides,setCurveOverrides] = useState<CurveOverrides>({});
  const [mapping,setMapping] = useState<any[]>([]), [useAI,setUseAI] = useState(true), [includeLocal,setIncludeLocal] = useState(true);
  const [autoCorrect,setAutoCorrect]=useState(true),[qualitySubmitting,setQualitySubmitting]=useState(false);
  const [refineSubmitting,setRefineSubmitting] = useState(false);
  const selectedRef = useRef<string | null>(null);
  const isReady = !!job?.metrics;
  const busy = qualitySubmitting || refineSubmitting || !!job && ['queued', 'decoding', 'analyzing','refining','correcting'].includes(job.status);
  const body = { style, strength, mode, overrides, curve_overrides:curveOverrides, white_balance:whiteBalance, use_ai:useAI, include_local:includeLocal };
  async function loadJobs() { const data = await json<Job[]>('/jobs'); setJobs(data); return data; }
  function restoreView(next:Job){
    const state=next.edit_state;
    setWhiteBalance(state?.white_balance??null);
    setStyle(state?.style||next.decision?.recommended_style||'natural');setStrength(state?.strength??.7);setMode(state?.mode||'photo');
    setUseAI(state?.use_ai??true);setIncludeLocal(state?.include_local??true);setOverrides(state?.overrides||{});setCurveOverrides(state?.curve_overrides||{});
  }
  function select(next: Job) {
    selectedRef.current = next.id; setJob(next); setOverrides({}); setWhiteBalance(null); setCurveOverrides({}); setProcessed(''); setOriginal('');
    restoreView(next); setIntent(''); setError('');
  }
  useEffect(() => { Promise.all([loadJobs(), json('/settings')]).then(([list, conf]) => { setSettings(conf); if (list[0]) select(list[0]); }).catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (!job || !['queued','decoding','analyzing','refining','correcting'].includes(job.status)) return;
    const id = job.id;
    const timer = setInterval(() => {
      json<Job>('/jobs/' + id).then(next => {
        if (selectedRef.current !== id) return;
        setJob(next);
        if (!['queued','decoding','analyzing','refining','correcting'].includes(next.status) && !next.error && ['analyzing','refining','correcting'].includes(job.status)) {if(job.status!=='correcting'||next.quality_report?.correction?.changed)restoreView(next);if(job.status==='refining')setNotice('AI 修改已应用，可查看修改明细或撤销。');if(job.status==='correcting')setNotice(next.quality_report?.correction?.reason||'效果检查已完成。');}
        if (!['queued', 'decoding', 'analyzing','refining','correcting'].includes(next.status)) loadJobs().catch(e => setError(e.message));
      }).catch(e => setError(e.message));
    }, 1000);
    return () => clearInterval(timer);
  }, [job?.id, job?.status]);
  useEffect(() => { setName('AI ' + styles.find(s => s.id === style)!.name); }, [style]);
  useEffect(() => {
    if (!job?.metrics) return;
    const controller = new AbortController();
    request(`/jobs/${job.id}/original`, { signal: controller.signal }).then(r => r.blob()).then(b => { if(!controller.signal.aborted)setOriginal(URL.createObjectURL(b)); }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => { controller.abort(); };
  }, [job?.id, isReady, job?.metrics?.preview_version]);
  useEffect(() => {
    if (!isReady || !job) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setRendering(true);
      try {
        const result = await json(`/jobs/${job.id}/parameters`, { ...post(body), signal: controller.signal });
        const blob = await (await request(`/jobs/${job.id}/preview`, { ...post(body), signal: controller.signal })).blob();
        if (controller.signal.aborted) return;
        setParams(result.parameters); setWhiteBalanceResult(result.white_balance); setCurves(result.curves); setNotes(result.notes); setMapping(result.mapping||[]); setProcessed(URL.createObjectURL(blob));
      } catch (e: any) { if (e.name !== 'AbortError') setError(e.message); }
      finally { if (!controller.signal.aborted) setRendering(false); }
    }, 220);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [job?.id, isReady, job?.decision, job?.regions, style, strength, mode, overrides, curveOverrides, whiteBalance, useAI, includeLocal]);
  async function importPhoto() {
    if (!raw) return;
    setUploading(true); setError('');
    try {
      const form = new FormData(); form.append('raw', raw); if (xmp) form.append('template', xmp);
      const next = await json<Job>('/jobs', { method: 'POST', body: form }); select(next); await loadJobs();
      setImportOpen(false); setRaw(null); setXmp(null);
    } catch (e: any) { setError(e.message); } finally { setUploading(false); }
  }
  async function analyze() {
    if (!job) return;
    if (!settings?.has_key) { setShowSettings(true); return; }
    try { setError(''); setJob(await json(`/jobs/${job.id}/analyze`, post({ intent,auto_correct:autoCorrect }))); }
    catch (e: any) { setError(e.message); }
  }
  async function checkQuality(correct=false,protect_manual=true){
    if(!job)return;const id=job.id;setQualitySubmitting(true);setError('');setNotice('');
    try{const next=await json<Job>(`/jobs/${id}/quality/${correct?'correct':'check'}`,post({state:body,protect_manual}));if(selectedRef.current===id)setJob(next);}
    catch(e:any){if(selectedRef.current===id)setError(e.message);}finally{setQualitySubmitting(false);}
  }
  async function refineCurrent(instruction:string){
    if(!job)return false;
    if(!settings?.has_key){setShowSettings(true);return false;}
    const id=job.id;setRefineSubmitting(true);setError('');setNotice('');
    try{const next=await json<Job>(`/jobs/${id}/refine`,post({instruction,state:body}));if(selectedRef.current===id)setJob(next);return true;}
    catch(e:any){if(selectedRef.current===id)setError(e.message);return false;}finally{setRefineSubmitting(false);}
  }
  async function undoAI(){
    if(!job)return;const id=job.id;setRefineSubmitting(true);setError('');
    try{const next=await json<Job>(`/jobs/${id}/refine/undo`,post({}));if(selectedRef.current===id){setJob(next);restoreView(next);setNotice('已撤销上次修改，恢复提交时的参数。');}await loadJobs();}
    catch(e:any){setError(e.message);}finally{setRefineSubmitting(false);}
  }
  async function exportPreset() {
    if (!job) return;
    setExporting(true); setError('');
    try {
      const response = await request(`/jobs/${job.id}/export`, post({ ...body, name }));
      const saved = await download(await response.blob(), name.replace(/[<>:"/\\|?*]/g, '_') + '.xmp');
      if (saved) { setNotice('XMP 已导出，可在 Camera Raw 的预设面板中导入。'); setTimeout(() => setNotice(''), 6000); }
    } catch (e: any) { setError(e.message); } finally { setExporting(false); }
  }
  async function removeJob(target: Job) {
    try { await json(`/jobs/${target.id}`, { method: 'DELETE' }); const list = await loadJobs(); if (job?.id === target.id) { if (list[0]) select(list[0]); else { setJob(null); selectedRef.current = null; } } }
    catch (e: any) { setError(e.message); }
  }
  return <div className="app" onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }} onDrop={e => { e.preventDefault(); setDragging(false); const files = [...e.dataTransfer.files]; setRaw(files.find(f => /\.nef$/i.test(f.name)) || null); setXmp(files.find(f => /\.xmp$/i.test(f.name)) || null); setImportOpen(true); }}>
    <aside className="sidebar">
      <div className="brand"><img src={appIcon} width={30} height={30} alt=""/><div>RAW STUDIO<small>AI 摄影后期助手</small></div></div>
      <button className="import-button" onClick={() => setImportOpen(true)}><ImagePlus size={18}/> 导入 NEF 照片</button>
      <div className="section-label">工作区 <span>{jobs.length.toString().padStart(2, '0')}</span></div>
      <div className="job-list">{jobs.map(item => <div className={'job-row ' + (job?.id === item.id ? 'active' : '')} key={item.id}>
        <button className="job-select" onClick={() => select(item)}><Layers3 size={17}/><span>{item.filename}<small>{statusNames[item.status]}</small></span></button>
        <button className="icon-button delete" aria-label={'删除 ' + item.filename} disabled={['queued', 'decoding', 'analyzing','refining','correcting'].includes(item.status)} onClick={() => removeJob(item)}><Trash2 size={13}/></button>
      </div>)}{!jobs.length && <div className="empty-history">从一张原片开始，<br/>让每次调色都有依据。</div>}</div>
      <div className="sidebar-bottom"><span className="local-dot"/> 本地处理 · NEF 原片留在本机</div>
      <button className="settings-button" onClick={() => setShowSettings(true)}><Settings2 size={17}/> 模型与 API 设置 <span className={'connection ' + (settings?.has_key ? 'connected' : '')}/></button>
    </aside>
    <main>
      <header><div><span className="eyebrow">YOUR FRAME. YOUR VISION.</span><h1>{job ? job.filename : '发现原片的另一种可能'}</h1></div><div className="header-meta">{job?.metadata?.camera || 'AI RAW STUDIO'}<span>CAMERA RAW 17.3</span></div></header>
      <div className="workflow"><span className={job ? 'done' : ''}>01 <b>导入原片</b></span><ChevronRight size={13}/><span className={isReady ? 'done' : ''}>02 <b>理解画面</b></span><ChevronRight size={13}/><span className={processed ? 'done' : ''}>03 <b>塑造风格</b></span><ChevronRight size={13}/><span>04 <b>导出预设</b></span></div>
      {(error || job?.error) && <div className="alert" role="alert">{error || job?.error}<button className="icon-button" onClick={() => { setError(''); if (job) setJob({ ...job, error: undefined }); }}><X size={15}/></button></div>}
      {notice && <div className="notice" role="status"><Check size={15}/>{notice}</div>}
      {!job ? <div className="welcome"><div className="welcome-aperture"><img src={appIcon} width={76} height={76} alt=""/></div><span className="eyebrow">FROM RAW TO REFINEMENT</span><h2>好的后期，从理解照片开始。</h2><p>分析光影、色彩与画面主题，<br/>为你的原片生成专属 Camera Raw 预设。</p><button className="primary" onClick={() => setImportOpen(true)}><FolderOpen size={18}/>选择 NEF 原片</button><small>也可以拖入 NEF 和 XMP 文件</small><div className="welcome-features"><span>本地 RAW 解码</span><span>DeepSeek 视觉分析</span><span>可编辑 XMP 预设</span></div></div> : <div className="workspace">
        <section className="canvas-column">
          <div className="panel-heading"><h2><ArrowLeftRight size={16}/>效果对比</h2><span>{rendering ? '正在更新预览…' : '近似预览 · 以 Camera Raw 为准'}</span></div>
          <div className="preview-canvas">
            {original ? <div className="compare"><img src={processed || original} alt="调整后近似预览"/><div className="before-layer" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}><img src={original} alt="原始解码预览"/></div><div className="split-line" style={{ left: split + '%' }}><span><ArrowLeftRight size={14}/></span></div><span className="image-tag before-tag">原片</span><span className="image-tag after-tag">{styles.find(s => s.id === style)?.name}</span><input aria-label="前后对比" className="compare-range" type="range" min="0" max="100" value={split} onChange={e => setSplit(+e.target.value)}/></div> : <div className="decode-state">{job.status === 'failed' ? <><ImagePlus size={30}/><p>照片未能解码，请重新导入。</p></> : <><LoaderCircle className="spin" size={30}/><p>正在解码 NEF 原片…</p></>}</div>}
          </div>
          <div className="photo-meta">{job.metadata && <><span>{job.metadata.width} × {job.metadata.height}</span><span>ISO {job.metadata.iso || '—'}</span><span>ƒ/{job.metadata.aperture || '—'}</span><span>{job.metadata.shutter || '—'} s</span></>}<span className="status-text">{statusNames[job.status]}</span></div>
          {isReady && <div className="technical"><div className="histogram"><div className="section-label">RGB 直方图 <span>解码预览</span></div><Histogram data={job.metrics.preview.histogram}/></div><div className="metric"><span>传感器近饱和采样</span><strong>{(job.metrics.sensor.saturated_fraction * 100).toFixed(2)}<small>%</small></strong></div><div className="metric"><span>预览暗部占比</span><strong>{(job.metrics.preview.shadow_fraction * 100).toFixed(1)}<small>%</small></strong></div></div>}
          {isReady && <AcrValidation key={"acr-"+job.id} job={job} state={body} disabled={!!busy} preview={processed||original}/>}
          {isReady && <FilmEditor key={"film-"+job.id} jobId={job.id} regions={job.regions} disabled={!!busy}/>}
          {isReady&&<QualityEditor job={job} state={body} disabled={!!busy} pending={qualitySubmitting||job.status==='correcting'} autoCorrect={autoCorrect} onAutoCorrect={setAutoCorrect} onCheck={()=>checkQuality()} onCorrect={(protect:boolean)=>checkQuality(true,protect)} onUndo={undoAI}/>}
          <section className="analysis-card"><div className="panel-heading"><h2><Sparkles size={16}/>画面解读</h2><span className="pill">{job.decision ? 'DeepSeek · 已分析' : '等待 AI 分析'}</span></div>{job.decision ? <><div className="analysis-grid">{[['主题', job.decision.scene], ['主体', job.decision.subject], ['光影', job.decision.lighting], ['情绪', job.decision.mood], ['构图', job.decision.composition]].map(([title, value]) => <div key={title}><small>{title}</small><p>{value}</p></div>)}</div><p className="rationale">{job.decision.rationale}</p>{!job.decision.editing_plan&&<p className="rationale">这是旧版分析记录，请点击“重新分析”生成完整参数计划和局部调整。</p>}<p className="crop">构图建议：{job.decision.crop_suggestion}（本版不执行裁切）</p></> : <p className="muted">本地曝光与色彩分析完成后，可调用 AI 理解主题、构图与光影，并推荐后期方向。</p>}
            <textarea aria-label="风格意向" placeholder="描述你想要的感觉，例如：保留自然肤色，让整体更有电影感…" value={intent} onChange={e => setIntent(e.target.value)} maxLength={1200}/><div className="ai-footer"><small>向 AI 发送缩小预览图与技术指标</small><button className="secondary" disabled={!isReady || !!busy} onClick={analyze}>{job.status === 'analyzing' ? <LoaderCircle className="spin" size={15}/> : <Sparkles size={15}/>} {job.status === 'analyzing' ? '分析中…' : job.decision ? '重新分析' : 'AI 分析'}</button></div>
          </section>
          {isReady && <RefinementEditor key={"refinement-"+job.id} job={job} disabled={!!busy} pending={refineSubmitting||job.status==='refining'} onSubmit={refineCurrent} onUndo={undoAI}/>}
          {isReady && mode==='photo' && <LocalEditor key={"local-"+job.id} job={job} original={original} processed={processed} disabled={!!busy} onError={setError} onChange={(next:Job)=>{if(selectedRef.current===next.id){setJob(next);setJobs(list=>list.map(item=>item.id===next.id?next:item));}}}/>}
          {isReady && <details className="parameter-mapping"><summary>查看 AI 决策到 XMP 参数的映射</summary><table><thead><tr><th>参数</th><th>实际值</th><th>来源与依据</th></tr></thead><tbody>{[...new Map(mapping.map(item=>[item.parameter,item])).values()].map((item:any)=><tr key={item.parameter}><td>{item.parameter}</td><td>{JSON.stringify(item.value)}</td><td>{item.source}<small>{item.reason}</small></td></tr>)}</tbody></table></details>}
          {job.warnings && <details className="limitations"><summary>处理说明与预览限制</summary>{job.warnings.map(w => <p key={w}>{w}</p>)}<p>近似预览模拟基础明暗、HSL、校准、四通道点曲线、参数曲线、分离色调和颗粒；不复刻 Adobe 配置文件、校准渲染、质感算法或降噪。</p><p>NEF 副本及历史保存在本机，可通过工作区的删除按钮清除。</p></details>}
        </section>
        <aside className="inspector"><fieldset className="inspector-controls" disabled={!isReady||!!busy}><div className="panel-heading"><h2><SlidersHorizontal size={16}/>后期方案</h2><span>01 / PRESET</span></div>
          <label className="checkbox"><input type="checkbox" checked={useAI} onChange={e=>{setUseAI(e.target.checked);setOverrides({}); setWhiteBalance(null); setCurveOverrides({});}}/>使用 AI 全局计划</label><label className="checkbox"><input type="checkbox" checked={includeLocal} disabled={mode!=='photo'} onChange={e=>setIncludeLocal(e.target.checked)}/>应用局部调整（照片专属）</label>
          <div className="style-list">{styles.map(s => <button key={s.id} className={'style-card ' + (style === s.id ? 'selected' : '')} disabled={!isReady} onClick={() => { setStyle(s.id); setOverrides({}); setWhiteBalance(null); setCurveOverrides({}); }}><span className={'style-swatch ' + s.id} style={{ backgroundColor: s.color }}/><span><b>{s.name}</b><small>{s.description}</small></span>{job.decision?.recommended_style === s.id && <em>推荐</em>}{style === s.id && <Check size={16}/>}</button>)}</div>
          <div className="control-heading"><label htmlFor="strength">风格强度</label><strong>{Math.round(strength * 100)}<small>%</small></strong></div><input id="strength" type="range" min="0" max="1" step=".05" disabled={!isReady} value={strength} onChange={e => { setStrength(+e.target.value); }}/><div className="range-captions"><span>轻微</span><span>鲜明</span></div>
          <div className="divider"/><div className="control-heading"><label>Camera Raw 参数</label><button className="text-button" disabled={!isReady} onClick={() => {setOverrides({}); setWhiteBalance(null);setCurveOverrides({});}}>全部恢复方案</button></div>
          <CameraRawPanels whiteBalance={whiteBalance} whiteBalanceResult={whiteBalanceResult} onWhiteBalance={value=>{setWhiteBalance(value);setOverrides(previous=>Object.fromEntries(Object.entries(previous).filter(([key])=>!['Temperature','Tint'].includes(key))));}} params={params} overrides={overrides} curves={curves} curveOverrides={curveOverrides} disabled={!isReady||!!busy} mode={mode} onOverride={(key,value)=>setOverrides(previous=>({...previous,[key]:value}))} onReset={keys=>setOverrides(previous=>Object.fromEntries(Object.entries(previous).filter(([key])=>!keys.includes(key))))} onCurve={(channel,points)=>setCurveOverrides(previous=>{const next={...previous};if(points)next[channel]=points;else delete next[channel];return next;})}/>
          <div className="divider"/><div className="control-heading"><label>导出模式</label><span className="tiny">.XMP</span></div><div className="export-modes"><button className={mode === 'photo' ? 'chosen' : ''} onClick={() => { setMode('photo'); setOverrides({}); setWhiteBalance(null); setCurveOverrides({}); }}><b>照片专属</b><small>含基础曝光纠正</small></button><button className={mode === 'style' ? 'chosen' : ''} onClick={() => { setMode('style'); setOverrides({}); setWhiteBalance(null); setCurveOverrides({}); }}><b>通用风格</b><small>适用于其他照片</small></button></div><label className="field-label" htmlFor="preset-name">预设名称</label><input id="preset-name" type="text" maxLength={100} value={name} onChange={e => setName(e.target.value)}/><button className="primary export" disabled={!isReady || exporting || !name.trim()} onClick={exportPreset}>{exporting ? <LoaderCircle className="spin" size={17}/> : <ArrowDownToLine size={17}/>}导出 XMP 预设</button><p className="export-note">在 Camera Raw「预设 → 导入预设」中加载。<br/>模板：ACR {job.template.version} / PV {job.template.process_version}</p>{notes.map(n => <p className="engine-note" key={n}>{n}</p>)}{isReady && !job.decision && <p className="engine-note">当前由本地规则生成，尚未使用 AI 分析。</p>}
        </fieldset></aside>
      </div>}
      <footer><span>AI RAW STUDIO <b>0.8.0</b></span><span>让技术服务于你的摄影直觉</span></footer>
    </main>
    {(importOpen || dragging) && <div className="modal-backdrop"><section className="modal import-modal"><button className="close icon-button" aria-label="关闭导入" onClick={() => { setImportOpen(false); setDragging(false); }}><X size={20}/></button><ImagePlus size={30} className="accent"/><h2>导入你的原片</h2><p className="muted">原片在本地解码，保留拍摄时的白平衡。</p><label className="file-picker"><FolderOpen size={22}/><b>{raw?.name || '选择或拖入 NEF 文件'}</b><small>最大 150 MB</small><input aria-label="NEF 文件" type="file" accept=".nef,.NEF" onChange={e => setRaw(e.target.files?.[0] || null)}/></label><label className="field-label">Camera Raw XMP 模板（可选）</label><input aria-label="XMP 模板" type="file" accept=".xmp" onChange={e => setXmp(e.target.files?.[0] || null)}/><p className="tiny muted">未选择模板时使用样片确定的 ACR 17.3 / PV 15.4。仅提取版本信息，不套用已有调色。</p><button className="primary" disabled={!raw || uploading} onClick={importPhoto}>{uploading ? <LoaderCircle className="spin" size={17}/> : <ImagePlus size={17}/>} {uploading ? '正在导入…' : '导入并分析原片'}</button></section></div>}
    {showSettings && <SettingsDialog initial={settings} onClose={() => setShowSettings(false)} onSaved={setSettings} onError={setError}/>}
  </div>;
}
function Histogram({ data }: { data: number[][] }) {
  const max = Math.max(...data.flat(), 1);
  return <svg viewBox="0 0 256 65" preserveAspectRatio="none" aria-label="RGB 直方图">{data.map((channel, i) => <path key={i} d={'M0 65 ' + channel.map((v, x) => `L${x * 256 / 63} ${65 - Math.sqrt(v / max) * 62}`).join(' ') + ' L256 65 Z'} fill={['#c77e76', '#94b6a0', '#769fcb'][i]} opacity=".45"/>)}</svg>;
}
function SettingsDialog({ initial, onClose, onSaved, onError }: any) {
  const [url, setUrl] = useState(initial?.base_url || 'https://api.deepseek.com'), [model, setModel] = useState(initial?.model || 'deepseek-flash');
  const [key, setKey] = useState(''), [remember, setRemember] = useState(false), [saving, setSaving] = useState(false), [message, setMessage] = useState('');
  async function save(clear = false) {
    setSaving(true); setMessage('');
    try { const data = await json('/settings', { ...post({ base_url: url, model, api_key: clear ? null : key || null, remember_key: remember, clear_key: clear }), method: 'PUT' }); onSaved(data); setKey(''); onClose(); }
    catch (e: any) { setMessage(e.message); onError(e.message); } finally { setSaving(false); }
  }
  return <div className="modal-backdrop"><section className="modal"><button className="close icon-button" aria-label="关闭设置" onClick={onClose}><X size={20}/></button><Settings2 className="accent" size={28}/><h2>连接视觉模型</h2><p className="muted">DeepSeek V4.1 Flash · 图像理解与风格决策</p><label className="field-label" htmlFor="base-url">API 服务地址</label><input id="base-url" type="url" value={url} onChange={e => setUrl(e.target.value)}/><label className="field-label" htmlFor="model">模型名称</label><input id="model" value={model} onChange={e => setModel(e.target.value)}/><label className="field-label" htmlFor="api-key">API Key {initial?.has_key && <span className="accent">· 已配置</span>}</label><input id="api-key" type="password" value={key} autoComplete="off" placeholder={initial?.has_key ? '留空以保留现有 Key' : '输入 DeepSeek API Key'} onChange={e => setKey(e.target.value)}/><label className="checkbox"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)}/>在 Windows 凭据管理器中记住新 Key</label><p className="tiny muted">默认仅在后端内存中保留新 Key。AI 分析会将最长边 1280 像素的预览图与技术指标发送至上方服务。</p>{message && <p className="form-error">{message}</p>}<div className="modal-actions">{initial?.has_key && <button className="text-button" disabled={saving} onClick={() => save(true)}>清除已保存 Key</button>}<button className="primary" disabled={saving} onClick={() => save()}>{saving ? '正在保存…' : '保存设置'}</button></div></section></div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
