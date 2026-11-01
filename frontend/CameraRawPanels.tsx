import React, { useEffect, useRef, useState } from 'react';

export type Channel = 'rgb'|'red'|'green'|'blue';
export type Point = {x:number;y:number};
export type Curves = Record<Channel,number[][]>;
export type CurveOverrides = Partial<Record<Channel,Point[]>>;
type Spec = readonly [string,string,number,number,number];
const colors = [['Red','红色','#cf7771'],['Orange','橙色','#d9a15f'],['Yellow','黄色','#d2c36c'],['Green','绿色','#8eb983'],['Aqua','浅绿色','#7bbdb8'],['Blue','蓝色','#7c9dc6'],['Purple','紫色','#a592cd'],['Magenta','洋红','#c48cb5']] as const;
const basic:Spec[] = [['Exposure2012','曝光',-2,2,.05],['Contrast2012','对比度',-100,100,1],['Highlights2012','高光',-100,100,1],['Shadows2012','阴影',-100,100,1],['Whites2012','白色',-100,100,1],['Blacks2012','黑色',-100,100,1],['Texture','纹理',-100,100,1],['Clarity2012','清晰度',-100,100,1],['Dehaze','去朦胧',-100,100,1],['Vibrance','自然饱和度',-100,100,1],['Saturation','饱和度',-100,100,1]];
const calibration:Spec[] = [['ShadowTint','阴影 · 色调',-100,100,1],...['Red','Green','Blue'].flatMap((color,i):Spec[]=>[[color+'Hue',['红','绿','蓝'][i]+'原色 · 色相',-100,100,1],[color+'Saturation',['红','绿','蓝'][i]+'原色 · 饱和度',-100,100,1]])];
const parametric:Spec[] = [['ParametricHighlights','高光区域',-100,100,1],['ParametricLights','亮调',-100,100,1],['ParametricDarks','暗调',-100,100,1],['ParametricShadows','阴影区域',-100,100,1]];
const grading:Spec[] = [['SplitToningShadowHue','阴影 · 色相',0,360,1],['SplitToningShadowSaturation','阴影 · 饱和度',0,100,1],['SplitToningHighlightHue','高光 · 色相',0,360,1],['SplitToningHighlightSaturation','高光 · 饱和度',0,100,1],['SplitToningBalance','平衡',-100,100,1],['ColorGradeGlobalHue','全局 · 色相',0,360,1],['ColorGradeGlobalSat','全局 · 饱和度',0,100,1]];
const effects:Spec[] = [['GrainAmount','颗粒 · 数量',0,100,1],['GrainSize','颗粒 · 大小',0,100,1],['GrainFrequency','颗粒 · 粗糙度',0,100,1]];
const linear = [[0,0],[255,255]];

function Numeric({value,min,max,step=1,label,disabled,onChange}:{value:number;min:number;max:number;step?:number;label:string;disabled?:boolean;onChange:(value:number)=>void}) {
  const [draft,setDraft]=useState(String(value));
  useEffect(()=>setDraft(String(value)),[value]);
  function commit(){const n=Number(draft);if(draft.trim()&&Number.isFinite(n)&&n>=min&&n<=max)onChange(Math.round(n/step)*step);else setDraft(String(value));}
  return <input className="acr-number" type="number" aria-label={label} min={min} max={max} step={step} disabled={disabled} value={draft} onChange={e=>setDraft(e.target.value)} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();if(e.key==='Escape'){e.preventDefault();setDraft(String(value));}}}/>;
}

type Props = {params:Record<string,number>;overrides:Record<string,number>;curves:Curves;curveOverrides:CurveOverrides;disabled:boolean;mode:string;onOverride:(key:string,value:number)=>void;onReset:(keys:string[])=>void;onCurve:(channel:Channel,points:Point[]|null)=>void};
export function CameraRawPanels(p:Props){
  const [hsl,setHsl]=useState('Hue'),[channel,setChannel]=useState<Channel>('rgb');
  const val=(key:string)=>p.overrides[key]??p.params[key]??0;
  function slider([key,label,min,max,step]:Spec){return <div className="acr-slider" key={key} title={key}><div><label htmlFor={key}>{label}</label><Numeric label={label+'数值'} value={val(key)} min={min} max={max} step={step} disabled={p.disabled} onChange={v=>p.onOverride(key,v)}/></div><input id={key} type="range" aria-label={label} min={min} max={max} step={step} disabled={p.disabled} value={val(key)} onChange={e=>p.onOverride(key,+e.target.value)}/></div>;}
  function panel(title:string,specs:Spec[],content?:React.ReactNode,open=false){return <details className="acr-panel" open={open||undefined}><summary>{title}</summary><div className="acr-panel-body"><button className="text-button acr-reset" disabled={p.disabled} onClick={()=>p.onReset(specs.map(s=>s[0]))}>恢复方案值</button><div className="sliders">{specs.map(slider)}</div>{content}</div></details>;}
  const splits:Spec[] = [['ParametricShadowSplit','阴影分界',10,Math.min(70,val('ParametricMidtoneSplit')-10),1],['ParametricMidtoneSplit','中间调分界',Math.max(20,val('ParametricShadowSplit')+10),Math.min(80,val('ParametricHighlightSplit')-10),1],['ParametricHighlightSplit','高光分界',Math.max(30,val('ParametricMidtoneSplit')+10),90,1]];
  return <div className="acr-panels">
    {panel('基本',basic.filter(([key])=>p.mode==='photo'||!['Exposure2012','Highlights2012','Shadows2012','Whites2012'].includes(key)),undefined,true)}
    <details className="acr-panel"><summary>颜色混合器 · HSL</summary><div className="acr-panel-body"><div className="acr-tabs" role="group" aria-label="HSL 分量">{[['Hue','色相'],['Saturation','饱和度'],['Luminance','明亮度']].map(([id,label])=><button className={hsl===id?'chosen':''} key={id} onClick={()=>setHsl(id)}>{label}</button>)}</div><button className="text-button acr-reset" disabled={p.disabled} onClick={()=>p.onReset(colors.flatMap(([c])=>['Hue','Saturation','Luminance'].map(kind=>kind+'Adjustment'+c)))}>恢复全部 HSL 方案值</button><div className="sliders">{colors.map(([color,label,swatch])=><div className="acr-color" key={color} style={{'--swatch':swatch} as React.CSSProperties}>{slider([hsl+'Adjustment'+color,label,-100,100,1])}</div>)}</div></div></details>
    <details className="acr-panel"><summary>曲线</summary><div className="acr-panel-body"><p className="acr-hint">点曲线与参数曲线可叠加。手动点曲线点击“应用曲线”后生效。</p><div className="acr-tabs" role="group" aria-label="点曲线通道">{(['rgb','red','green','blue'] as Channel[]).map((c,i)=><button className={channel===c?'chosen':''} key={c} onClick={()=>setChannel(c)}>{['RGB','红','绿','蓝'][i]}</button>)}</div><CurveEditor key={channel} channel={channel} points={p.curves?.[channel]??linear} disabled={p.disabled} manual={!!p.curveOverrides[channel]} onApply={points=>p.onCurve(channel,points)} onReset={()=>p.onCurve(channel,null)}/><div className="acr-subheading">参数曲线 <button className="text-button" disabled={p.disabled} onClick={()=>p.onReset([...parametric,...splits].map(s=>s[0]))}>恢复方案值</button></div><div className="sliders">{[...parametric,...splits].map(slider)}</div></div></details>
    {panel('校准',calibration,<p className="acr-hint">三原色调整会影响整体色彩关系。处理版本沿用 XMP 模板；本地预览近似模拟校准，最终效果以 Camera Raw 为准。</p>)}
    {panel('色彩分级',grading,<p className="acr-hint">当前支持阴影、高光、全局和平衡。</p>)}
    {panel('效果 · 颗粒',effects)}
  </div>;
}

function CurveEditor({channel,points,disabled,manual,onApply,onReset}:{channel:Channel;points:number[][];disabled:boolean;manual:boolean;onApply:(points:Point[])=>void;onReset:()=>void}){
  const [draft,setDraft]=useState<number[][]>(points),[selected,setSelected]=useState(0);
  const [dirty,setDirty]=useState(false);
  const dragging=useRef(false);
  const signature=JSON.stringify(points);
  useEffect(()=>{setDraft(points.map(p=>[...p]));setSelected(0);setDirty(false);},[signature]);
  const color={rgb:'#c4d5c9',red:'#d68a83',green:'#98c296',blue:'#8faee2'}[channel];
  function change(index:number,x:number,y:number){setDraft(previous=>{const next=previous.map(p=>[...p]);const lo=previous[index-1],hi=previous[index+1];next[index]=[index===0?0:index===previous.length-1?255:Math.max(lo[0]+1,Math.min(hi[0]-1,Math.round(x))),Math.max(lo?.[1]??0,Math.min(hi?.[1]??255,Math.round(y)))];return next;});setDirty(true);}
  function coord(e:React.PointerEvent<SVGSVGElement>){const r=e.currentTarget.getBoundingClientRect();return [Math.max(0,Math.min(255,(e.clientX-r.left)/r.width*255)),Math.max(0,Math.min(255,255-(e.clientY-r.top)/r.height*255))];}
  function add(){if(draft.length>=12)return;const gaps=draft.slice(0,-1).map((p,i)=>({i,gap:draft[i+1][0]-p[0]})).sort((a,b)=>b.gap-a.gap);const i=gaps[0].i;const x=Math.round((draft[i][0]+draft[i+1][0])/2),y=Math.round((draft[i][1]+draft[i+1][1])/2);setDraft([...draft.slice(0,i+1),[x,y],...draft.slice(i+1)]);setSelected(i+1);setDirty(true);}
  return <div className="curve-editor"><svg viewBox="0 0 255 255" className="curve-graph" aria-label={`${channel.toUpperCase()} 点曲线`} role="img" onPointerMove={e=>{if(dragging.current&&!disabled){const [x,y]=coord(e);change(selected,x,y);}}} onPointerUp={()=>{dragging.current=false;}} onPointerCancel={()=>{dragging.current=false;}}>
    <rect width="255" height="255" fill="#131b16"/>{[64,128,192].map(v=><g key={v} stroke="#35433a" strokeWidth=".7"><path d={`M${v} 0V255 M0 ${v}H255`}/></g>)}<path d="M0 255L255 0" stroke="#4c6153" strokeDasharray="3 4" fill="none"/>
    <polyline points={draft.map(([x,y])=>`${x},${255-y}`).join(' ')} fill="none" stroke={color} strokeWidth="2"/>{draft.map(([x,y],i)=><circle key={i} cx={x} cy={255-y} r={i===selected?5:3.5} fill={color} stroke="#131b16" strokeWidth="1" onPointerDown={e=>{if(disabled)return;e.preventDefault();setSelected(i);dragging.current=true;e.currentTarget.ownerSVGElement?.setPointerCapture(e.pointerId);}}/>)}</svg>
    <div className="curve-coordinates"><label>控制点<select aria-label="曲线控制点" disabled={disabled} value={selected} onChange={e=>setSelected(+e.target.value)}>{draft.map((p,i)=><option key={i} value={i}>{i+1}</option>)}</select></label><label>输入<Numeric label="曲线输入" value={draft[selected][0]} min={selected===0?0:draft[selected-1][0]+1} max={selected===draft.length-1?255:draft[selected+1][0]-1} disabled={disabled||selected===0||selected===draft.length-1} onChange={x=>change(selected,x,draft[selected][1])}/></label><label>输出<Numeric label="曲线输出" value={draft[selected][1]} min={draft[selected-1]?.[1]??0} max={draft[selected+1]?.[1]??255} disabled={disabled} onChange={y=>change(selected,draft[selected][0],y)}/></label></div>
    <div className="curve-actions"><button disabled={disabled||draft.length>=12} onClick={add}>添加点</button><button disabled={disabled||selected===0||selected===draft.length-1} onClick={()=>{setDraft(draft.filter((_,i)=>i!==selected));setSelected(0);setDirty(true);}}>删除点</button><button disabled={disabled} onClick={()=>{setDraft(linear.map(p=>[...p]));setSelected(0);setDirty(true);}}>直线</button></div>
    <div className="curve-actions"><button className="secondary" disabled={disabled||!dirty} onClick={()=>{onApply(draft.map(([x,y])=>({x,y})));setDirty(false);}}>应用曲线</button><button className="text-button" disabled={disabled||(!manual&&!dirty)} onClick={()=>{onReset();setDraft(points.map(p=>[...p]));setSelected(0);setDirty(false);}}>恢复方案曲线</button></div>{dirty&&<p className="acr-hint" role="status">曲线已修改，尚未应用。</p>}
  </div>;
}
