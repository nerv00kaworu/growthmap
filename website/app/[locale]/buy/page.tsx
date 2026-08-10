import {localizedMetadata} from '../../../content/metadata';
import {core,parseLocale} from '../../../content/i18n';
import {buyPlans} from '../../../content/buy-content';
import {notFound} from 'next/navigation';

export const generateMetadata=({params}:{params:Promise<{locale:string}>})=>localizedMetadata(params,'buy');

export default async function BuyPage({params}:{params:Promise<{locale:string}>}){
  const locale=parseLocale((await params).locale);if(!locale)notFound();
  const c=core[locale].buy;
  const plans=buyPlans[locale];
  return <section className="page buy-page">
    <p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><p className="lead">{c.lead}</p>
    <section className="plan-section" aria-labelledby="plan-comparison">
      <h2 id="plan-comparison" className="comparison-lead">{plans.comparisonLead}</h2>
      <p className="sr-only">{plans.plansLabel}</p>
      <div className="plan-grid">
        <article className="plan-card">
          <header><h3>{plans.free.name}</h3><span className="plan-badge">{plans.free.badge}</span></header>
          <p className="plan-summary">{plans.free.summary}</p>
          <ul>{plans.free.features.map(feature=><li key={feature}>{feature}</li>)}</ul>
          <p className="plan-quota">{plans.free.quota}</p>
          <p className="plan-fit">{plans.free.fit}</p>
        </article>
        <article className="plan-card plan-personal">
          <header><div><h3>{plans.personal.name}</h3><span className="plan-badge">{plans.personal.badge}</span></div><strong className="plan-price">{plans.personal.price}</strong></header>
          <p className="plan-summary">{plans.personal.summary}</p>
          <ul>{plans.personal.features.map(feature=><li key={feature}>{feature}</li>)}</ul>
          <p className="plan-quota">{plans.personal.quota}</p>
          <p className="allocation-notice">{plans.personal.allocation}</p>
          <p className="plan-fit">{plans.personal.fit}</p>
        </article>
      </div>
    </section>
    <ol className="payment-flow">{c.stages.map((stage:string,i:number)=><li key={stage} className={i===0?'current':''}><b>0{i+1}</b><span>{stage}</span><em>{i===0?c.current:c.locked}</em></li>)}</ol>
    <p className="notice">{c.guard}</p><button disabled aria-disabled="true">{c.disabled}</button>
  </section>
}
