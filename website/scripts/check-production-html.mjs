import assert from 'node:assert/strict';
const base=process.env.GROWTHMAP_TEST_BASE||'http://127.0.0.1:3310';
const expected={'zh-TW':'zh-Hant','zh-CN':'zh-Hans',en:'en'};
for(const [locale,lang] of Object.entries(expected))for(const path of ['','features','agents','security','download','buy','docs','docs/developers']){const url=`${base}/${locale}${path?`/${path}`:''}`,response=await fetch(url);assert.equal(response.status,200,url);const html=await response.text();assert.match(html,new RegExp(`^<!DOCTYPE html><html lang="${lang}"`),`root lang: ${url}`);assert.equal((html.match(/<h1/g)||[]).length,1,`one H1: ${url}`);for(const token of ['<title>','name="description"','property="og:title"','name="twitter:card"','hrefLang="x-default"','growthmap-share.png'])assert.ok(html.includes(token),`${token}: ${url}`)}
const unknown={
 'zh-TW':{lang:'zh-Hant',title:'找不到頁面｜GrowthMap',h1:'找不到這個頁面',body:'這個網址不存在，或頁面已經移動。',home:'返回首頁',features:'怎麼使用'},
 'zh-CN':{lang:'zh-Hans',title:'找不到页面｜GrowthMap',h1:'找不到这个页面',body:'这个网址不存在，或页面已经移动。',home:'返回首页',features:'怎么使用'},
 en:{lang:'en',title:'Page not found | GrowthMap',h1:'Page not found',body:'This address does not exist, or the page has moved.',home:'Return home',features:'How it works'}
};
for(const [locale,copy] of Object.entries(unknown)){const url=`${base}/${locale}/unknown-route`,response=await fetch(url),html=await response.text();assert.equal(response.status,404,url);assert.match(html,new RegExp(`^<!DOCTYPE html><html lang="${copy.lang}"`));assert.equal((html.match(/<title>/g)||[]).length,1);assert.equal((html.match(/<h1>/g)||[]).length,1);for(const value of Object.values(copy))assert.ok(html.includes(value),`${value}: ${url}`);assert.ok(html.includes('noindex, nofollow'),`noindex: ${url}`)}
for(const asset of ['/media/home/overview-growth.webm','/og/growthmap-share.png','/icon-192.png']){const response=await fetch(`${base}${asset}`);assert.equal(response.status,200,asset);assert.equal(response.headers.get('cache-control'),'public, max-age=3600, must-revalidate',asset)}
const home=await fetch(`${base}/en`).then(response=>response.text()),staticAsset=home.match(/(?:src|href)="(\/_next\/static\/[^"]+)"/)?.[1];assert.ok(staticAsset,'content-hashed Next static asset');const staticResponse=await fetch(`${base}${staticAsset}`);assert.equal(staticResponse.headers.get('cache-control'),'public, max-age=31536000, immutable',staticAsset);
console.log('production HTML: 24 localized routes plus trilingual raw 404 and exact cache headers passed');
