import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const root=path.resolve(import.meta.dirname,'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const {buyPlans}=await import(pathToFileURL(path.join(root,'content/buy-content.ts')));
const leaves=value=>typeof value==='string'?[value]:Array.isArray(value)?value.flatMap(leaves):value&&typeof value==='object'?Object.values(value).flatMap(leaves):[];
const shape=value=>Array.isArray(value)?['array',...value.map(shape)]:value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,shape(value[key])])):typeof value;

test('buy plans have exact trilingual typed content parity',()=>{for(const locale of ['zh-CN','en'])assert.deepEqual(shape(buyPlans[locale]),shape(buyPlans['zh-TW']),locale)});
test('Free is forever with every core feature and one active slot, not one stored project',()=>{const free=buyPlans.en.free;assert.match(free.badge,/Free forever.*All core features/);for(const term of ['GUI','Tree','Graph','Branch','Mainline','Node','AI Expand','Deepen','compatible agents','discussions as nodes','read outcomes back','Export','backup'])assert.ok(leaves(free).join(' ').includes(term),term);assert.match(free.quota,/1 project active at a time/);assert.match(free.quota,/does not mean you can create or store only one project/);assert.match(free.quota,/archive or delete/);for(const available of ['Reading','search','export','backup'])assert.ok(free.quota.includes(available),available)});
test('Personal only adds active quota, devices, license, and same-major updates',()=>{const personal=leaves(buyPlans.en.personal).join(' ');assert.match(personal,/Includes everything in Free/);for(const term of ['Unlimited simultaneously active projects','2 personal devices','named issuer target','Perpetual major v1 license','same major version'])assert.ok(personal.includes(term),term);assert.match(buyPlans.en.personal.quota,/Core features do not change/);for(const forbidden of ['cloud sync','one-click agent','exclusive AI'])assert.ok(!personal.toLowerCase().includes(forbidden),forbidden)});
test('price allocation requires worldwide payment confirmation and quote reserves nothing',()=>{const price=buyPlans.en.personal.allocation;assert.match(price,/first 50 payment-confirmed allocations worldwide.*US\$10/);assert.match(price,/51 onward.*US\$29/);assert.match(price,/quote does not reserve an allocation/)});
test('buy remains offline and disabled with no real order path',()=>{const page=read('app/[locale]/buy/page.tsx'),core=read('content/i18n.ts');assert.ok(page.includes('disabled aria-disabled="true"'));for(const forbidden of ['fetch(','axios','wallet','credentials','createOrder','onClick='])assert.ok(!page.includes(forbidden),forbidden);for(const truth of ['no wallet connection','creates no real order'])assert.ok(core.includes(truth),truth)});
test('English contains no CJK and simplified Chinese avoids reviewed traditional forms',()=>{const cjk=/[\u3400-\u9fff]/u;for(const text of leaves(buyPlans.en))assert.ok(!cjk.test(text),text);const traditionalOnly=/[與個為裡檔節點實會這還開後總說將讓從線導備網權據復歸劃啟專購]/u;for(const text of leaves(buyPlans['zh-CN']))assert.ok(!traditionalOnly.test(text),text)});
