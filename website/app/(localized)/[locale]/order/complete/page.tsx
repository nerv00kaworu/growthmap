import Link from 'next/link';
import {notFound} from 'next/navigation';
import {parseLocale,core} from '../../../../../content/i18n';

export const dynamic='force-dynamic';
export const revalidate=0;
export const fetchCache='force-no-store';
export const metadata={robots:{index:false,follow:false}};

export default async function OrderCompletePage({params}:{params:Promise<{locale:string}>}){
  const locale=parseLocale((await params).locale);if(!locale)notFound();
  const c=core[locale].order;
  return <section className="page order-complete">
    <p className="eyebrow">{c.eyebrow}</p><h1>{c.title}</h1><p className="lead">{c.lead}</p>
    <p className="notice">{c.verification}</p><p>{c.hint}</p>
    <p className="actions"><Link className="button" href={`/${locale}/support`}>{c.support}</Link><Link href={`/${locale}/buy`}>{c.retry}</Link></p>
  </section>
}
