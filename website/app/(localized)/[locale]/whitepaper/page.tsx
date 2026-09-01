import {notFound} from 'next/navigation';
import {parseLocale} from '../../../../content/i18n';
import {localizedMetadata} from '../../../../content/metadata';
import {WhitepaperDocument} from '../../../../components/WhitepaperDocument';
import {readHumanWhitepaper} from '../../../../lib/whitepaper';
export const generateMetadata=({params}:{params:Promise<{locale:string}>})=>localizedMetadata(params,'whitepaper');
export default async function Whitepaper({params}:{params:Promise<{locale:string}>}){const locale=parseLocale((await params).locale);if(!locale)notFound();return <WhitepaperDocument locale={locale} source={readHumanWhitepaper(locale)} kind="human"/>}
