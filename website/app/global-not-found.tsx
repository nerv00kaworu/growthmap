import type {Metadata} from 'next';import Link from 'next/link';import './styles.css';
export const metadata:Metadata={title:'找不到頁面｜GrowthMap',robots:{index:false,follow:false}};
export default function GlobalNotFound(){return <html lang="zh-Hant"><body><main className="not-found"><Link className="brand" href="/zh-TW"><i/>GrowthMap</Link><p className="eyebrow">404</p><h1>找不到這個頁面</h1><p className="lead">這個網址不存在，或頁面已經移動。</p><nav className="actions" aria-label="404 導覽"><Link className="button" href="/zh-TW">返回首頁</Link><Link href="/zh-TW/features">怎麼使用</Link></nav></main></body></html>}
