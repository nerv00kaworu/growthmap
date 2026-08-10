import Link from 'next/link'; import {core,type Locale} from '../content/i18n'; import {Detailed} from './ProductContent'; import {HomeLanding} from './HomeLanding';
const href=(l:Locale,p:string)=>`/${l}${p==='/'?'':p}`;
export function Home({locale}:{locale:Locale}){return <HomeLanding locale={locale}/>}
export function Product({locale}:{locale:Locale}){return <Detailed locale={locale} page="product"/>}
export function Download({locale}:{locale:Locale}){const copy=core[locale].download;return <section className="page"><p className="eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1><p className="lead">{copy.lead}</p></section>}
export function Pricing({locale}:{locale:Locale}){const c=core[locale].pricing;return <section className="page"><p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><div className="price"><p>{c.first}</p><strong>US$10</strong><p>{c.after}</p></div><ul>{c.terms.map((x:string)=><li key={x}>{x}</li>)}</ul><p className="notice">{c.notice}</p><Link className="button" href={href(locale,'/buy')}>{c.demo}</Link></section>}
