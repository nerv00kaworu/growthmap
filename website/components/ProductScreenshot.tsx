import Image from 'next/image';import type {Locale} from '../content/i18n';
const copy={
'zh-TW':{alt:'GrowthMap 已驗證 Windows 候選版本的封裝介面',caption:'已驗證的 Windows 封裝候選畫面；不是公開正式版畫面。'},
'zh-CN':{alt:'GrowthMap 已验证 Windows 候选版本的封装界面',caption:'已验证的 Windows 封装候选画面；不是公开正式版画面。'},
en:{alt:'Packaged interface from a verified GrowthMap Windows candidate',caption:'Verified packaged Windows candidate interface. This is not a public production-release image.'}} as const;
export function ProductScreenshot({locale}:{locale:Locale}){const c=copy[locale];return <figure className="product-shot"><Image src="/media/product/growthmap-windows-candidate.jpg" width={1255} height={811} loading="lazy" sizes="(max-width: 720px) 92vw, 1008px" alt={c.alt}/><figcaption>{c.caption}</figcaption></figure>}
