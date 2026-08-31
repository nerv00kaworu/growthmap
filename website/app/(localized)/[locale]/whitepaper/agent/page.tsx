import {notFound} from 'next/navigation';
import {parseLocale} from '../../../../../content/i18n';
import {localizedMetadata} from '../../../../../content/metadata';
import {WhitepaperDocument} from '../../../../../components/WhitepaperDocument';
import {readAgentWhitepaper} from '../../../../../lib/whitepaper';
export const generateMetadata=({params}:{params:Promise<{locale:string}>})=>localizedMetadata(params,'whitepaper/agent');
export default async function AgentWhitepaper({params}:{params:Promise<{locale:string}>}){const locale=parseLocale((await params).locale);if(!locale)notFound();return <WhitepaperDocument locale={locale} source={readAgentWhitepaper()} kind="agent"/>}
