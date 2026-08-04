'use client';
import {useState} from 'react';
import {core,type Locale} from '../content/i18n';

const nodeLabels={
  'zh-TW':['專案目標','產品分支','Agent 提案','實作讀回'],
  'zh-CN':['项目目标','产品分支','Agent 提案','实现读回'],
  en:['Project goal','Product branch','Agent proposal','Implementation readback']
} as const;
const statusLabels={
  'zh-TW':['人類定義專案目標、成功條件與限制。','從專案目標長出產品分支，整理相關模組與工作。','Agent 取得 Context Packet，提出可供人類審核的變更。','Commit、測試、決策與風險證據回填到原節點。'],
  'zh-CN':['人类定义项目目标、成功条件与限制。','从项目目标长出产品分支，整理相关模块与工作。','Agent 获取 Context Packet，提出可供人类审核的变更。','Commit、测试、决策与风险证据回填到原节点。'],
  en:['A person defines the project goal, success criteria, and constraints.','A product branch grows from the goal and organizes related modules and work.','An agent reads the Context Packet and proposes a change for human review.','Commit, tests, decisions, and risk evidence return to the source node.']
} as const;

export function DemoMap({locale}:{locale:Locale}){
  const c=core[locale].agents,labels=nodeLabels[locale],descriptions=statusLabels[locale];
  const [mode,setMode]=useState<'tree'|'graph'>('tree');const [step,setStep]=useState(0);
  const steps=labels;
  return <section className="page demo">
    <p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><p className="lead">{c.lead}</p>
    <div className="demo-controls" role="group" aria-label={c.caption}><button className={mode==='tree'?'selected':''} aria-pressed={mode==='tree'} onClick={()=>setMode('tree')}>{c.tree}</button><button className={mode==='graph'?'selected':''} aria-pressed={mode==='graph'} onClick={()=>setMode('graph')}>{c.graph}</button></div>
    <div className={'demo-canvas '+mode} aria-label={c.caption}>
      <svg viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true"><path d={mode==='tree'?'M14 30 L40 15 M14 30 L40 45 M40 15 L66 35 M40 45 L66 35 M66 35 L88 22':'M14 30 C28 4 48 8 66 20 M14 30 C30 56 52 52 66 38 M66 20 L88 30 M66 38 L88 30 M40 12 L40 48'}/></svg>
      {labels.map((label,i)=><button key={label} className={`demo-node d${i} ${step>=i?'active':''}`} aria-pressed={step===i} onClick={()=>setStep(i)}><span>{String(i+1).padStart(2,'0')}</span>{label}</button>)}
    </div>
    <div className="stepper">{steps.map((label:string,i:number)=><button className={step===i?'selected':''} aria-pressed={step===i} onClick={()=>setStep(i)} key={label}><b>0{i+1}</b><span>{label}</span></button>)}</div>
    <div className="demo-explainer" role="status"><b>{steps[step]}</b><p>{descriptions[step]}</p></div>
    <p className="caption">{c.caption}</p>
  </section>
}
