import {localizedMetadata} from '../../../content/metadata'; export const generateMetadata=({params}:{params:Promise<{locale:string}>})=>localizedMetadata(params,'buy'); import {core,parseLocale} from '../../../content/i18n';
import {notFound} from 'next/navigation';

const stateLabels={
  'zh-TW':{current:'目前階段',locked:'尚未開放'},
  'zh-CN':{current:'当前阶段',locked:'尚未开放'},
  en:{current:'Current stage',locked:'Locked'}
} as const;

export default async function BuyPage({params}:{params:Promise<{locale:string}>}){
  const locale=parseLocale((await params).locale);if(!locale)notFound();
  const c=core[locale].buy,state=stateLabels[locale];
  return <section className="page"><p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><p className="lead">{c.lead}</p><ol className="payment-flow">{c.stages.map((stage:string,i:number)=><li key={stage} className={i===0?'current':''}><b>0{i+1}</b><span>{stage}</span><em>{i===0?state.current:state.locked}</em></li>)}</ol><p className="notice">{c.guard}</p><button disabled aria-disabled="true">{c.disabled}</button></section>
}
