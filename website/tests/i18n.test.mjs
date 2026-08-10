import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const root=path.resolve(import.meta.dirname,'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const {workflowContent}=await import(pathToFileURL(path.join(root,'content/workflows.ts')));
const {core,defaultLocale,labels,localeOrFallback,locales,parseLocale}=await import(pathToFileURL(path.join(root,'content/i18n.ts')));

const shape=value=>Array.isArray(value)?['array',...value.map(shape)]:value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,shape(value[key])])):typeof value;

test('deep locale catalogs have exact runtime shape parity anchored to zh-TW',()=>{
  for(const catalog of [core,labels,workflowContent]) for(const locale of locales) assert.deepEqual(shape(catalog[locale]),shape(catalog['zh-TW']),`${locale} catalog drift`);
});

test('locale parsing and unknown/missing fallback are deterministic',()=>{
  assert.equal(defaultLocale,'zh-TW');
  for(const locale of locales){assert.equal(parseLocale(locale),locale);assert.equal(localeOrFallback(locale),locale)}
  for(const invalid of [undefined,'','zh','zh-TW-x','EN','unknown']) assert.equal(localeOrFallback(invalid),'zh-TW');
  assert.equal(parseLocale('unknown'),undefined);
});

test('catalog contract is strongly typed and component-local copy is migrated',()=>{
  const i18n=read('content/i18n.ts'),localized=read('components/Localized.tsx'),buy=read('app/(localized)/[locale]/buy/page.tsx');
  assert.ok(i18n.includes('satisfies Record<Locale,CoreCatalog>'));
  assert.ok(!i18n.includes('Record<string,any>'));
  assert.ok(!localized.includes("locale==='zh-TW'?"));
  assert.ok(!buy.includes('stateLabels'));
  assert.ok(!read('content/legal.ts').includes('授权 activation'));
  assert.ok(read('content/legal.ts').includes('授权启用'));
});

const leaves=value=>typeof value==='string'?[value]:Array.isArray(value)?value.flatMap(leaves):value&&typeof value==='object'?Object.values(value).flatMap(leaves):[];
test('workflow locale leaves are translated and catalogs do not alias zh-TW objects',()=>{
  const cjk=/[\u3400-\u9fff]/u;
  for(const text of leaves(workflowContent.en)) assert.ok(!cjk.test(text),`English workflow contains CJK: ${text}`);
  const traditionalOnly=/[與個為裡檔節點實會這還開後總說將讓從線導備網權據復歸劃]/u;
  for(const text of leaves(workflowContent['zh-CN'])) assert.ok(!traditionalOnly.test(text),`zh-CN workflow contains reviewed traditional form: ${text}`);
  for(const locale of ['en','zh-CN']) for(const page of Object.keys(workflowContent['zh-TW'])){
    assert.notStrictEqual(workflowContent[locale][page],workflowContent['zh-TW'][page],`${locale}.${page} page aliases zh-TW`);
    assert.notStrictEqual(workflowContent[locale][page].sections,workflowContent['zh-TW'][page].sections,`${locale}.${page}.sections aliases zh-TW`);
    for(let index=0;index<workflowContent['zh-TW'][page].sections.length;index++){
      assert.notStrictEqual(workflowContent[locale][page].sections[index],workflowContent['zh-TW'][page].sections[index],`${locale}.${page}.sections[${index}] aliases zh-TW`);
      assert.notStrictEqual(workflowContent[locale][page].sections[index].items,workflowContent['zh-TW'][page].sections[index].items,`${locale}.${page}.items aliases zh-TW`);
    }
  }
});
