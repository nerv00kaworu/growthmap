'use client';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import type {Locale} from '../content/i18n';
import {homeContent} from '../content/home-content';import {StructuredData} from './StructuredData';

const href=(locale:Locale,path:string)=>`/${locale}${path}`;
type DemoKind='overview'|'gui'|'conversation';
type DemoMedia={video:string;poster:string};
export const homeMedia={
  'zh-TW':{
    overview:{video:'/media/home/overview-growth.webm',poster:'/media/home/overview-growth-poster.jpg'},
    gui:{video:'/media/home/gui-growth.webm',poster:'/media/home/gui-growth-poster.jpg'},
    conversation:{video:'/media/home/agent-conversation.webm',poster:'/media/home/agent-conversation-poster.jpg'}
  },
  'zh-CN':{
    overview:{video:'/media/home/overview-growth.zh-CN.webm',poster:'/media/home/overview-growth.zh-CN.jpg'},
    gui:{video:'/media/home/gui-growth.zh-CN.webm',poster:'/media/home/gui-growth.zh-CN.jpg'},
    conversation:{video:'/media/home/agent-conversation.zh-CN.webm',poster:'/media/home/agent-conversation.zh-CN.jpg'}
  },
  en:{
    overview:{video:'/media/home/overview-growth.en.webm',poster:'/media/home/overview-growth.en.jpg'},
    gui:{video:'/media/home/gui-growth.en.webm',poster:'/media/home/gui-growth.en.jpg'},
    conversation:{video:'/media/home/agent-conversation.en.webm',poster:'/media/home/agent-conversation.en.jpg'}
  }
} as const satisfies Record<Locale,Record<DemoKind,DemoMedia>>;

function DemoVideo({locale,kind,label,play,pause}:{locale:Locale;kind:DemoKind;label:string;play:string;pause:string}){
  const media=homeMedia[locale][kind];
  const ref=useRef<HTMLVideoElement>(null);const [playing,setPlaying]=useState(false);
  useEffect(()=>{const video=ref.current;if(!video)return;const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');const observer=new IntersectionObserver(entries=>{if(entries[0]?.isIntersecting&&!reduced.matches){void video.play().catch(()=>{});}else video.pause();},{threshold:.35});const stop=()=>{if(reduced.matches)video.pause()};reduced.addEventListener('change',stop);observer.observe(video);return()=>{observer.disconnect();reduced.removeEventListener('change',stop)}},[]);
  return <figure className="home-video-card"><video ref={ref} muted loop playsInline controls controlsList="nodownload" preload="metadata" poster={media.poster} aria-label={label} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)}><source src={media.video} type="video/webm"/></video><noscript><a href={media.video}>{label}</a></noscript><button type="button" className="home-video-toggle" aria-label={playing?pause:play} onClick={()=>{const video=ref.current;if(!video)return;if(video.paused)void video.play();else video.pause()}}>{playing?'Ⅱ':'▶'}</button><figcaption>{label}</figcaption></figure>
}

export function HomeLanding({locale}:{locale:Locale}){const copy=homeContent[locale];return <><StructuredData locale={locale}/>
  <section className="home-hero"><div><p className="eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1><p className="lead">{copy.lead}</p><div className="actions"><a className="button" href="#two-workflows">{copy.primary}</a><a className="textlink" href="#project-example">{copy.secondary} →</a></div><p className="home-micro">{copy.micro}</p></div><DemoVideo locale={locale} kind="overview" label={copy.overviewLabel} play={copy.play} pause={copy.pause}/></section>
  <section className="home-section" id="two-workflows"><header className="home-section-head"><p className="eyebrow">{copy.pathsEyebrow}</p><h2>{copy.pathsTitle}</h2><p>{copy.pathsLead}</p></header><div className="home-paths">{copy.paths.map((path,index)=><article className="home-path" key={path.label}><span>{path.label}</span><h3>{path.title}</h3><p>{path.body}</p><div className="home-path-flow">{path.flow.map((item,i)=><span key={item}>{i>0&&<i aria-hidden="true">→</i>}<b>{item}</b></span>)}</div><DemoVideo locale={locale} kind={index===0?'gui':'conversation'} label={`${path.label} · ${copy.demoLabel}`} play={copy.play} pause={copy.pause}/></article>)}</div><p className="home-converge">{copy.converge}</p><p className="home-demo-note">{copy.demoNote}</p></section>
  <section className="home-section"><header className="home-section-head"><p className="eyebrow">{copy.governanceEyebrow}</p><h2>{copy.governanceTitle}</h2></header><div className="home-steps">{copy.steps.map(step=><article key={step.label}><span>{step.label}</span><h3>{step.title}</h3><p>{step.body}</p></article>)}</div></section>
  <section className="home-example" id="project-example"><div><p className="eyebrow">{copy.exampleEyebrow}</p><h2>{copy.exampleTitle}</h2><p>{copy.exampleBody}</p></div><div className="home-tree"><ul><li><span>{copy.tree[0].label} <small>{copy.tree[0].type}</small></span><ul><li><span>{copy.tree[1].label} <small>{copy.tree[1].type}</small></span></li><li><span>{copy.tree[2].label} <small>{copy.tree[2].type}</small></span><ul><li><span>{copy.tree[3].label} <small>{copy.tree[3].type}</small></span></li><li className="home-evidence"><span>{copy.tree[4].label} <em>{copy.tree[4].evidence}</em></span></li></ul></li><li><span>{copy.tree[5].label} <small>{copy.tree[5].type}</small></span></li><li><span>{copy.tree[6].label} <small>{copy.tree[6].type}</small></span></li></ul></li></ul></div></section>
  <section className="home-section"><header className="home-section-head"><p className="eyebrow">{copy.focusEyebrow}</p><h2>{copy.focusTitle}</h2></header><div className="home-focus">{copy.focusCards.map(card=><article key={card.title}><h3>{card.title}</h3><p>{card.body}</p></article>)}</div></section>
  <section className="home-section home-boundary"><header className="home-section-head"><p className="eyebrow">{copy.boundaryEyebrow}</p><h2>{copy.boundaryTitle}</h2></header><div className="home-boundary-grid">{copy.boundaries.map(card=><article key={card.title}><h3>{card.title}</h3><p>{card.body}</p></article>)}</div></section>
  <section className="home-closing"><h2>{copy.closing}</h2><p>{copy.closingLead}</p><Link className="button" href={href(locale,'/features')}>{copy.explore}</Link></section>
</>}
