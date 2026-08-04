'use client';
import {useState} from 'react';
import {core,type Locale} from '../content/i18n';

const nodeLabels={
  'zh-TW':['專案目標','產品分支','Agent 提案','實作讀回'],
  'zh-CN':['项目目标','产品分支','Agent 提案','实现读回'],
  en:['Project goal','Product branch','Agent proposal','Implementation readback']
} as const;
const statusLabels={
  'zh-TW':['人類修正目標與限制','Agent 取得 context packet 並提交原子變更','Commit、測試與風險證據回到節點'],
  'zh-CN':['人类修正目标与限制','Agent 获取 context packet 并提交原子变更','Commit、测试与风险证据回到节点'],
  en:['A person corrects the goal and constraints','An agent reads a context packet and proposes an atomic change','Commit, tests, and risk evidence return to the node']
} as const;

export function DemoMap({locale}:{locale:Locale}){
  const c=core[locale].agents,labels=nodeLabels[locale],descriptions=statusLabels[locale];
  const [mode,setMode]=useState<'tree'|'graph'>('tree');const [step,setStep]=useState(0);
  const steps=[c.human,c.agent,c.readback];
  return <section className="page demo">
    <p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><p className="lead">{c.lead}</p>
    <div className="demo-controls" role="group" aria-label={c.caption}><button className={mode==='tree'?'selected':''} aria-pressed={mode==='tree'} onClick={()=>setMode('tree')}>{c.tree}</button><button className={mode==='graph'?'selected':''} aria-pressed={mode==='graph'} onClick={()=>setMode('graph')}>{c.graph}</button></div>
    <div className={'demo-canvas '+mode} aria-label={c.caption}>
      <svg viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true"><path d={mode==='tree'?'M14 30 L40 15 M14 30 L40 45 M40 15 L66 35 M40 45 L66 35 M66 35 L88 22':'M14 30 C28 4 48 8 66 20 M14 30 C30 56 52 52 66 38 M66 20 L88 30 M66 38 L88 30 M40 12 L40 48'}/></svg>
      {labels.map((label,i)=><button key={label} className={`demo-node d${i} ${step>=Math.max(0,i-1)?'active':''}`} aria-pressed={step===Math.min(i,2)} onClick={()=>setStep(Math.min(i,2))}><span>{String(i+1).padStart(2,'0')}</span>{label}</button>)}
    </div>
    <div className="stepper">{steps.map((label:string,i:number)=><button className={step===i?'selected':''} aria-pressed={step===i} onClick={()=>setStep(i)} key={label}><b>0{i+1}</b><span>{label}</span></button>)}</div>
    <div className="demo-explainer" role="status"><b>{steps[step]}</b><p>{descriptions[step]}</p></div>
    <p className="caption">{c.caption}</p>
  </section>
}
