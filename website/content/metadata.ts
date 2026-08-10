import type {Metadata} from 'next';
import {locales,parseLocale,type Locale} from './i18n';
import {site} from './site';

export const canonicalPages=['','features','agents','security','download','buy','docs','docs/developers','readback','support','status','privacy','terms','refund'] as const;
type PageKey=typeof canonicalPages[number];
type Entry={title:string;description:string};
const descriptions={
 'zh-TW':'GrowthMap 本機優先專案工作區：讓人類與相容 Agent 在可治理、可追溯的地圖上協作。',
 'zh-CN':'GrowthMap 本地优先项目工作区：让人类与兼容 Agent 在可治理、可追溯的地图上协作。',
 en:'GrowthMap is a local-first project workspace where people and compatible agents collaborate on a governed, traceable map.'
} satisfies Record<Locale,string>;
const titles:Record<Locale,Record<PageKey,string>>={
 'zh-TW':{'':'GrowthMap｜讓想法長成成果',features:'功能與工作方式｜GrowthMap',agents:'與 Agent 協作｜GrowthMap',security:'安全性與資料邊界｜GrowthMap',download:'Windows 候選版本狀態｜GrowthMap',buy:'Free 與 Personal v1｜GrowthMap',docs:'使用文件｜GrowthMap','docs/developers':'Agent Port 開發者文件｜GrowthMap',readback:'實作讀回｜GrowthMap',support:'支援｜GrowthMap',status:'服務狀態｜GrowthMap',privacy:'隱私政策｜GrowthMap',terms:'使用條款｜GrowthMap',refund:'退款政策｜GrowthMap'},
 'zh-CN':{'':'GrowthMap｜让想法成长为成果',features:'功能与工作方式｜GrowthMap',agents:'与 Agent 协作｜GrowthMap',security:'安全性与数据边界｜GrowthMap',download:'Windows 候选版本状态｜GrowthMap',buy:'Free 与 Personal v1｜GrowthMap',docs:'使用文档｜GrowthMap','docs/developers':'Agent Port 开发者文档｜GrowthMap',readback:'实现读回｜GrowthMap',support:'支持｜GrowthMap',status:'服务状态｜GrowthMap',privacy:'隐私政策｜GrowthMap',terms:'使用条款｜GrowthMap',refund:'退款政策｜GrowthMap'},
 en:{'':'GrowthMap | Let ideas grow into outcomes',features:'Features and workflows | GrowthMap',agents:'Work with agents | GrowthMap',security:'Security and data boundaries | GrowthMap',download:'Windows candidate status | GrowthMap',buy:'Free and Personal v1 | GrowthMap',docs:'User docs | GrowthMap','docs/developers':'Agent Port developer docs | GrowthMap',readback:'Implementation readback | GrowthMap',support:'Support | GrowthMap',status:'Service status | GrowthMap',privacy:'Privacy policy | GrowthMap',terms:'Terms of use | GrowthMap',refund:'Refund policy | GrowthMap'}
};
export const pageMetadataCatalog=Object.fromEntries(locales.map(locale=>[locale,Object.fromEntries(canonicalPages.map(page=>[page,{title:titles[locale][page],description:`${titles[locale][page]} — ${descriptions[locale]}`}]))])) as Record<Locale,Record<PageKey,Entry>>;
export async function localizedMetadata(params:Promise<{locale:string}>,path=''):Promise<Metadata>{
 const locale=parseLocale((await params).locale);if(!locale)return {};
 const key=(canonicalPages as readonly string[]).includes(path)?path as PageKey:'';const entry=pageMetadataCatalog[locale][key];const suffix=path?`/${path}`:'';const url=`/${locale}${suffix}`;
 const languages={...Object.fromEntries(locales.map(item=>[item,`/${item}${suffix}`])),'x-default':`/zh-TW${suffix}`};
 return {title:entry.title,description:entry.description,alternates:{canonical:url,languages},openGraph:{title:entry.title,description:entry.description,url,type:'website',locale:locale==='zh-TW'?'zh_TW':locale==='zh-CN'?'zh_CN':'en_US',images:[{url:'/og/growthmap-share.png',width:1200,height:630,alt:'GrowthMap'}]},twitter:{card:'summary_large_image',title:entry.title,description:entry.description,images:['/og/growthmap-share.png']}};
}
