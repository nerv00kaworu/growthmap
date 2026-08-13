import Link from 'next/link';
import {notFound} from 'next/navigation';
import {localizedMetadata} from '../../../../content/metadata';
import {parseLocale} from '../../../../content/i18n';
import {licenseContent} from '../../../../content/license-content';

export const generateMetadata=({params}:{params:Promise<{locale:string}>})=>localizedMetadata(params,'license');

export default async function LicensePage({params}:{params:Promise<{locale:string}>}){
  const locale=parseLocale((await params).locale);if(!locale)notFound();const c=licenseContent[locale];
  return <section className="page buy-page license-page">
    <p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><p className="lead">{c.lead}</p>
    <section className="plan-section" aria-labelledby="license-plans">
      <h2 id="license-plans" className="comparison-lead">{c.plansLabel}</h2>
      <div className="plan-grid">
        <article className="plan-card plan-personal">
          <header><div><h3>{c.early}</h3><span className="plan-badge">{c.earlyBadge}</span></div><strong className="plan-price">{c.earlyPrice}</strong></header>
          <p className="plan-summary">{c.earlyBody}</p>
          <a className="button" href="https://whop.com/growthmap/growthmap-early/" rel="noreferrer">{c.buyEarly}</a>
        </article>
        <article className="plan-card">
          <header><div><h3>{c.standard}</h3><span className="plan-badge">{c.standardBadge}</span></div><strong className="plan-price">{c.standardPrice}</strong></header>
          <p className="plan-summary">{c.standardBody}</p>
          <a className="button" href="https://whop.com/growthmap/growthmap/" rel="noreferrer">{c.buyStandard}</a>
        </article>
      </div>
    </section>
    <section className="license-details"><div><h2>{c.includedTitle}</h2><ul>{c.included.map(x=><li key={x}>{x}</li>)}</ul></div><div><h2>{c.flowTitle}</h2><ol>{c.flow.map(x=><li key={x}>{x}</li>)}</ol></div></section>
    <p><Link className="button" href={`/${locale}/download`}>{c.download}</Link></p>
  </section>;
}
