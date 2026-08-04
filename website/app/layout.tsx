import type {Metadata} from 'next'; import './styles.css'; import {site} from '../content/site';
const base=site.canonicalBase ? new URL(site.canonicalBase) : undefined;
export const metadata:Metadata={title:{default:'GrowthMap',template:'%s｜GrowthMap'},description:'A local-first shared project-growth workspace for people and arbitrary AI agents.',metadataBase:base,robots:{index:Boolean(base),follow:Boolean(base)},openGraph:{title:'GrowthMap',description:'A readable map for project growth.',type:'website'}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
