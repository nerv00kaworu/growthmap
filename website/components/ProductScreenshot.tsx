import Image from 'next/image';import type {Locale} from '../content/i18n';
const copy={
'zh-TW':{alt:'GrowthMap GrowthMap Windows 封裝介面',caption:'GrowthMap Windows 封裝介面。'},
'zh-CN':{alt:'GrowthMap GrowthMap Windows 封装界面',caption:'GrowthMap Windows 封装界面。'},
en:{alt:'Packaged GrowthMap Windows interface',caption:'Packaged GrowthMap Windows interface.'}} as const;
export function ProductScreenshot({locale}:{locale:Locale}){const c=copy[locale];return <figure className="product-shot"><Image src="/media/product/growthmap-windows-candidate.jpg" width={1255} height={811} loading="lazy" sizes="(max-width: 720px) 92vw, 1008px" alt={c.alt}/><figcaption>{c.caption}</figcaption></figure>}
