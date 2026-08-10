import type {Metadata} from 'next';import Link from 'next/link';
export const metadata:Metadata={title:'Page not found | GrowthMap',robots:{index:false,follow:false}};
export default function NotFound(){return <section className="not-found"><p className="eyebrow">404 · GrowthMap</p><h1>Page not found／找不到頁面／找不到页面</h1><p className="lead">Return to GrowthMap or learn how it works.</p><nav className="actions" aria-label="404 navigation"><Link className="button" href=".">Home／首頁／首页</Link><Link href="./features">How it works／怎麼使用／怎么使用</Link></nav></section>}
