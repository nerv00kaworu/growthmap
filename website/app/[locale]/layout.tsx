import {notFound} from 'next/navigation';
import Link from 'next/link';
import {locales,labels,parseLocale} from '../../content/i18n';
import {LocaleNav} from '../../components/LocaleNav';

export function generateStaticParams(){return locales.map(locale=>({locale}))}

const footerCopy={
  'zh-TW':{tagline:'人類與任意 Agent 共用的專案生長工作區。',local:'桌面專案資料永遠留在你的本機。',status:'狀態',skip:'跳到主要內容',nav:'主要導覽'},
  'zh-CN':{tagline:'人类与任意 Agent 共用的项目生长工作区。',local:'桌面项目数据始终留在你的本机。',status:'状态',skip:'跳到主要内容',nav:'主要导航'},
  en:{tagline:'A shared project-growth workspace for people and arbitrary agents.',local:'Desktop project data stays on your machine.',status:'Status',skip:'Skip to main content',nav:'Primary navigation'}
} as const;

export default async function LocaleLayout({children,params}:{children:React.ReactNode;params:Promise<{locale:string}>}){
  const locale=parseLocale((await params).locale);if(!locale)notFound();
  const n=labels[locale],copy=footerCopy[locale];
  const links:[string,string][]=[[n.product,'/ai-neutral'],[n.agents,'/showcase'],[n.download,'/download'],[n.pricing,'/buy'],[n.docs,'/docs'],[n.support,'/support']];
  const lang=locale==='zh-TW'?'zh-Hant':locale==='zh-CN'?'zh-Hans':'en';
  return <div lang={lang}>
    <a className="skip" href="#main">{copy.skip}</a>
    <header className="header">
      <Link className="brand" href={`/${locale}`} aria-label={`GrowthMap · ${n.home}`}><i/>GrowthMap</Link>
      <nav className="primary-nav" aria-label={copy.nav}>
        <div className="nav-links">{links.map(([name,p])=><Link key={p} href={`/${locale}${p}`}>{name}</Link>)}</div>
        <LocaleNav/>
      </nav>
    </header>
    <main id="main">{children}</main>
    <footer>
      <div><b>GrowthMap</b><p>{copy.tagline}</p><small>{copy.local}</small></div>
      <nav aria-label={copy.nav}><Link href={`/${locale}/security`}>{n.security}</Link><Link href={`/${locale}/support`}>{n.support}</Link><Link href={`/${locale}/status`}>{copy.status}</Link></nav>
      <p>nerv00kaworu@gmail.com · <a href="https://x.com/nerv00kaworu">@nerv00kaworu</a></p>
    </footer>
  </div>
}
