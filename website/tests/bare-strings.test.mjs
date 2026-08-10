import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const root=path.resolve(import.meta.dirname,'..');
const files=[
  'app/[locale]/layout.tsx',...fs.readdirSync(path.join(root,'app/[locale]'),{withFileTypes:true}).filter(x=>x.isDirectory()).map(x=>`app/[locale]/${x.name}/page.tsx`),
  'components/DemoMap.tsx','components/HomeLanding.tsx','components/LocaleNav.tsx','components/Localized.tsx','components/ProductContent.tsx','components/ProofSections.tsx'
];
// Exact exceptions only: brand/contact identity and compact technical/display tokens.
const allowed=new Set(['GrowthMap','nerv00kaworu@gmail.com','@nerv00kaworu','nerv00kaworu@gmail.com ·','→','▶','Ⅱ','US$10','01 /','02 /','03 /','04 /',' / ']);
const ordinary=/[A-Za-z]{2,}|[\u3400-\u9fff]/u;
function candidates(source){
  const found=[];
  for(const match of source.matchAll(/>((?:[^<>{}\n])+)</g)) found.push(match[1].trim());
  for(const match of source.matchAll(/\b(?:aria-label|alt|title|placeholder)=(?:"([^"]+)"|'([^']+)')/g)) found.push((match[1]??match[2]).trim());
  return found.filter(text=>text&&!/[{};]/.test(text));
}
test('localized user-visible JSX has no bare ordinary English or CJK copy',()=>{
  const violations=[];
  for(const file of files) for(const text of candidates(fs.readFileSync(path.join(root,file),'utf8'))) if(ordinary.test(text)&&!allowed.has(text)) violations.push(`${file}: ${JSON.stringify(text)}`);
  assert.deepEqual(violations,[],'Move copy to a typed locale catalog or add a narrowly reviewed exact token allowance.');
});

test('scanner catches ordinary English and CJK in JSX text and visible props',()=>{
  assert.deepEqual(candidates('<button>Buy now</button><img aria-label="下载应用" />'),['Buy now','下载应用']);
});
