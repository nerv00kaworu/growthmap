import type {MetadataRoute} from 'next';import {site,primaryRoutes} from '../content/site';import {locales} from '../content/i18n';
const contextualRoutes=['/docs','/support','/status','/privacy','/terms','/refund'];
export default function sitemap():MetadataRoute.Sitemap{if(!site.canonicalBase)return [];return [...primaryRoutes,...contextualRoutes].flatMap(route=>locales.map(locale=>({url:`${site.canonicalBase}/${locale}${route}`,lastModified:new Date('2026-08-07'),alternates:{languages:Object.fromEntries(locales.map(l=>[l,`${site.canonicalBase}/${l}${route}`]))}})))}
