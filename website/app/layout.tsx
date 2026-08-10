import type {Metadata} from 'next';import {headers} from 'next/headers';import './styles.css';import './home.css';import {site} from '../content/site';
const base=new URL(site.canonicalBase||'https://growthmap.app');
export const metadata:Metadata={metadataBase:base,robots:{index:Boolean(site.canonicalBase),follow:Boolean(site.canonicalBase)}};
export default async function RootLayout({children}:{children:React.ReactNode}){const locale=(await headers()).get('x-growthmap-locale');const lang=locale==='zh-CN'?'zh-Hans':locale==='en'?'en':'zh-Hant';return <html lang={lang}><body>{children}</body></html>}
