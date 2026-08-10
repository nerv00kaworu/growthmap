import Image from 'next/image';import type {Locale} from '../content/i18n';
const copy={
'zh-TW':{alt:'GrowthMap 已驗證 Windows 候選版本的封裝介面',caption:'已驗證的 packaged Windows candidate screenshot；這是候選畫面，不代表公開最新版 production release。'},
'zh-CN':{alt:'GrowthMap 已验证 Windows 候选版本的封装界面',caption:'已验证的 packaged Windows candidate screenshot；这是候选画面，不代表公开的最新 production release。'},
en:{alt:'Packaged interface from a verified GrowthMap Windows candidate',caption:'Verified packaged Windows candidate screenshot. This candidate image is not a claim about a latest public production release.'}} as const;
export function ProductScreenshot({locale}:{locale:Locale}){const c=copy[locale];return <figure className="product-shot"><Image src="/media/product/growthmap-windows-candidate.png" width={1008} height={681} loading="lazy" sizes="(max-width: 720px) 92vw, 1008px" alt={c.alt}/><figcaption>{c.caption}</figcaption></figure>}
