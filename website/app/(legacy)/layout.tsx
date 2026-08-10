import type {Metadata} from 'next';import '../styles.css';import '../home.css';import {site} from '../../content/site';
const base=new URL(site.canonicalBase||'https://growthmap.app');
export const metadata:Metadata={metadataBase:base,robots:{index:Boolean(site.canonicalBase),follow:Boolean(site.canonicalBase)}};
export default function LegacyLayout({children}:{children:React.ReactNode}){return <html lang="zh-Hant"><body>{children}</body></html>}
