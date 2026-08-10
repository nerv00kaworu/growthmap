import type {MetadataRoute} from 'next';
import {site} from '../../content/site';

export default function robots():MetadataRoute.Robots{
  if(!site.canonicalBase)return {rules:{userAgent:'*',disallow:'/'}};
  return {rules:{userAgent:'*',allow:'/'},sitemap:`${site.canonicalBase}/sitemap.xml`,host:site.canonicalBase};
}
