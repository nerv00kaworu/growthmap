import Link from 'next/link';
import type {Locale} from '../content/i18n';
import {workflowContent} from '../content/workflows';import {ProductScreenshot} from './ProductScreenshot';

const related={
'zh-TW':{agents:'與 Agent 協作',security:'查看安全性',download:'查看下載狀態'},
'zh-CN':{agents:'与 Agent 协作',security:'查看安全性',download:'查看下载状态'},
en:{agents:'Work with agents',security:'View security',download:'View download status'}} as const;
export function WorkflowPage({locale,page}:{locale:Locale;page:keyof typeof workflowContent.en}){
 const content=workflowContent[locale][page];
 return <section className={`page detailed workflow-page workflow-${page}`}><p className="eyebrow">{content.eyebrow}</p><h1>{content.title}</h1><p className="lead">{content.lead}</p>{page==='features'&&<ProductScreenshot locale={locale}/>} {content.sections.map((section,index)=><section className="workflow-section" key={section.title}><h2>{String(index+1).padStart(2,'0')} / {section.title}</h2><div className="workflow-page-grid">{section.items.map(item=><article key={item.title}><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></section>)}{content.cta&&<Link className="button" href={`/${locale}${content.cta.href}`}>{content.cta.label}</Link>}{page==='features'&&<nav className="actions" aria-label={related[locale].download}><Link href={`/${locale}/agents`}>{related[locale].agents}</Link><Link href={`/${locale}/security`}>{related[locale].security}</Link><Link href={`/${locale}/download`}>{related[locale].download}</Link></nav>}{(page==='agents'||page==='security'||page==='developers')&&<nav className="actions" aria-label={related[locale].download}><Link href={`/${locale}/security`}>{related[locale].security}</Link><Link href={`/${locale}/download`}>{related[locale].download}</Link></nav>}</section>
}
