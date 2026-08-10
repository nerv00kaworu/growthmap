import Link from 'next/link';
import type {Locale} from '../content/i18n';
import {workflowContent} from '../content/workflows';

export function WorkflowPage({locale,page}:{locale:Locale;page:keyof typeof workflowContent.en}){
 const content=workflowContent[locale][page];
 return <section className={`page detailed workflow-page workflow-${page}`}><p className="eyebrow">{content.eyebrow}</p><h1>{content.title}</h1><p className="lead">{content.lead}</p>{content.sections.map((section,index)=><section className="workflow-section" key={section.title}><h2>{String(index+1).padStart(2,'0')} / {section.title}</h2><div className="workflow-page-grid">{section.items.map(item=><article key={item.title}><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></section>)}{content.cta&&<Link className="button" href={`/${locale}${content.cta.href}`}>{content.cta.label}</Link>}</section>
}
