import assert from 'node:assert/strict';
const base=process.env.GROWTHMAP_TEST_BASE||'http://127.0.0.1:3310';
const expected={'zh-TW':'zh-Hant','zh-CN':'zh-Hans',en:'en'};
for(const [locale,lang] of Object.entries(expected))for(const path of ['','features','agents','security','download','buy','docs','docs/developers']){const url=`${base}/${locale}${path?`/${path}`:''}`,response=await fetch(url);assert.equal(response.status,200,url);const html=await response.text();assert.match(html,new RegExp(`^<!DOCTYPE html><html lang="${lang}"`),`root lang: ${url}`);assert.equal((html.match(/<h1/g)||[]).length,1,`one H1: ${url}`);for(const token of ['<title>','name="description"','property="og:title"','name="twitter:card"','hrefLang="x-default"','growthmap-share.png'])assert.ok(html.includes(token),`${token}: ${url}`)}
console.log('production HTML: 24 localized routes passed root lang, metadata, 200, and one-H1 checks');
