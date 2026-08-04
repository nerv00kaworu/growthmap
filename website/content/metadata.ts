import type {Metadata} from 'next';
import {locales,parseLocale} from './i18n';

export async function localizedMetadata(params:Promise<{locale:string}>,path=''):Promise<Metadata>{
  const locale=parseLocale((await params).locale);
  if(!locale)return {};
  const suffix=path?`/${path}`:'';
  const languages=Object.fromEntries(locales.map(item=>[item,`/${item}${suffix}`]));
  return {alternates:{canonical:`/${locale}${suffix}`,languages},openGraph:{locale:locale==='zh-TW'?'zh_TW':locale==='zh-CN'?'zh_CN':'en_US'}};
}
