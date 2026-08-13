import Link from 'next/link';
import {notFound} from 'next/navigation';
import {localizedMetadata} from '../../../../content/metadata';
import {parseLocale} from '../../../../content/i18n';
import {licenseContent} from '../../../../content/license-content';

export const generateMetadata=({params}:{params:Promise<{locale:string}>})=>localizedMetadata(params,'license');

export default async function LicensePage({params}:{params:Promise<{locale:string}>}){
  const locale=parseLocale((await params).locale);if(!locale)notFound();const c=licenseContent[locale];
  return <section className="page buy-page">
    <p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><p className="lead">{c.lead}</p>
    <section className="plan-section"><div className="plan-grid">
      <article className="plan-card plan-personal"><header><div><h2>{c.early}</h2></div></header><p>{c.earlyBody}</p><a className="button" href="https://whop.com/growthmap/growthmap-early/" rel="noreferrer">{c.buyEarly}</a></article>
      <article className="plan-card"><header><div><h2>{c.standard}</h2></div></header><p>{c.standardBody}</p><a className="button" href="https://whop.com/growthmap/growthmap/" rel="noreferrer">{c.buyStandard}</a></article>
    </div></section>
    <section><h2>{c.includedTitle}</h2><ul>{c.included.map(x=><li key={x}>{x}</li>)}</ul></section>
    <section><h2>{c.flowTitle}</h2><ol>{c.flow.map(x=><li key={x}>{x}</li>)}</ol></section>
    <section><h2>{c.friendTitle}</h2><p className="notice">{c.friendBody}</p></section>
    <section><h2>{c.updatesTitle}</h2><p>{c.updatesBody}</p></section>
    <p><Link className="button" href={`/${locale}/download`}>{c.download}</Link></p>
  </section>;
}
