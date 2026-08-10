import {notFound} from 'next/navigation';
import Link from 'next/link';
import {locales,labels,parseLocale} from '../../content/i18n';
import {LocaleNav} from '../../components/LocaleNav';
export function generateStaticParams(){return locales.map(locale=>({locale}))}
const footerCopy={
  'zh-TW':{tagline:'人類與任意 Agent 共用的專案生長工作區。',local:'桌面專案資料留在你的本機；公開網站不會接收專案資料。',status:'狀態',privacy:'隱私',terms:'條款',refund:'退款',skip:'跳到主要內容',nav:'主要導覽',menu:'選單'},
  'zh-CN':{tagline:'人类与任意 Agent 共用的项目生长工作区。',local:'桌面项目数据留在你的本机；公开网站不会接收项目数据。',status:'状态',privacy:'隐私',terms:'条款',refund:'退款',skip:'跳到主要内容',nav:'主要导航',menu:'菜单'},
  en:{tagline:'A project-growth workspace for people and compatible agents.',local:'Desktop project data stays on your machine; the public website does not receive project data.',status:'Status',privacy:'Privacy',terms:'Terms',refund:'Refunds',skip:'Skip to main content',nav:'Primary navigation',menu:'Menu'}
} as const;
export default async function LocaleLayout({children,params}:{children:React.ReactNode;params:Promise<{locale:string}>}){
 const locale=parseLocale((await params).locale);if(!locale)notFound();const n=labels[locale],copy=footerCopy[locale];
 const links:[string,string][]=[[n.home,''],[n.features,'/features'],[n.agents,'/agents'],[n.security,'/security'],[n.download,'/download'],[n.buy,'/buy']];const lang=locale==='zh-TW'?'zh-Hant':locale==='zh-CN'?'zh-Hans':'en';
 return <div lang={lang}><a className="skip" href="#main">{copy.skip}</a><header className="header"><Link className="brand" href={`/${locale}`} aria-label={`GrowthMap · ${n.home}`}><i/>GrowthMap</Link><nav className="primary-nav" aria-label={copy.nav}><div className="nav-links">{links.map(([name,p])=><Link key={p} href={`/${locale}${p}`}>{name}</Link>)}</div><details className="mobile-nav"><summary>{copy.menu}</summary><div className="mobile-nav-links">{links.map(([name,p])=><Link key={p} href={`/${locale}${p}`}>{name}</Link>)}</div></details><LocaleNav/></nav></header><main id="main">{children}</main><footer><div><b>GrowthMap</b><p>{copy.tagline}</p><small>{copy.local}</small></div><nav aria-label={copy.nav}><Link href={`/${locale}/docs`}>{n.docs}</Link><Link href={`/${locale}/support`}>{n.support}</Link><Link href={`/${locale}/status`}>{copy.status}</Link><Link href={`/${locale}/privacy`}>{copy.privacy}</Link><Link href={`/${locale}/terms`}>{copy.terms}</Link><Link href={`/${locale}/refund`}>{copy.refund}</Link></nav><p>nerv00kaworu@gmail.com · <a href="https://x.com/nerv00kaworu">@nerv00kaworu</a></p></footer></div>
}
