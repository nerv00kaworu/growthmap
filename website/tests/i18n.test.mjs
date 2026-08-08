import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const root=path.resolve(import.meta.dirname,'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const {core,defaultLocale,labels,localeOrFallback,locales,parseLocale}=await import(pathToFileURL(path.join(root,'content/i18n.ts')));

const shape=value=>Array.isArray(value)?['array',...value.map(shape)]:value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,shape(value[key])])):typeof value;

test('deep locale catalogs have exact runtime shape parity anchored to zh-TW',()=>{
  for(const catalog of [core,labels]) for(const locale of locales) assert.deepEqual(shape(catalog[locale]),shape(catalog['zh-TW']),`${locale} catalog drift`);
});

test('locale parsing and unknown/missing fallback are deterministic',()=>{
  assert.equal(defaultLocale,'zh-TW');
  for(const locale of locales){assert.equal(parseLocale(locale),locale);assert.equal(localeOrFallback(locale),locale)}
  for(const invalid of [undefined,'','zh','zh-TW-x','EN','unknown']) assert.equal(localeOrFallback(invalid),'zh-TW');
  assert.equal(parseLocale('unknown'),undefined);
});

test('catalog contract is strongly typed and component-local copy is migrated',()=>{
  const i18n=read('content/i18n.ts'),localized=read('components/Localized.tsx'),buy=read('app/[locale]/buy/page.tsx');
  assert.ok(i18n.includes('satisfies Record<Locale,CoreCatalog>'));
  assert.ok(!i18n.includes('Record<string,any>'));
  assert.ok(!localized.includes("locale==='zh-TW'?"));
  assert.ok(!buy.includes('stateLabels'));
  assert.ok(!read('content/legal.ts').includes('授权 activation'));
  assert.ok(read('content/legal.ts').includes('授权启用'));
});
