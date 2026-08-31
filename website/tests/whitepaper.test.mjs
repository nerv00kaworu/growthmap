import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');
const humanLocales=['zh-TW','zh-CN','en'];
const humanFiles=humanLocales.map(locale=>`content/whitepapers/growthmap-user-whitepaper.${locale}.md`);

test('human whitepaper has three complete localized editions',()=>{
 for(const file of humanFiles){const body=read(file);assert.ok(body.length>10000,`${file} is unexpectedly short`);for(const marker of ['Project','Node','Agent','AI'])assert.ok(body.includes(marker),`${file} missing ${marker}`);assert.ok(!body.includes('# 第三部：Agent 使用手冊'),`${file} embeds the old LLM manual`)}
});

test('agent whitepaper is one LLM-first canonical edition',()=>{
 const body=read('content/whitepapers/growthmap-agent-llm-onboarding.md');assert.ok(body.length>18000);for(const tool of ['capabilities','list_projects','read_project','read_graph','get_context','propose','apply_batch','report_event','submit_readback'])assert.ok(body.includes(`\`${tool}\``),`agent guide missing ${tool}`);for(const op of ['create_node','update_node','create_edge','create_content_block','create_branch'])assert.ok(body.includes(`\`${op}\``),`agent guide missing ${op}`);
});

test('whitepaper routes, metadata, sitemap and locale navigation are wired',()=>{
 const metadata=read('content/metadata.ts'),sitemap=read('app/(legacy)/sitemap.ts'),layout=read('app/(localized)/[locale]/layout.tsx');
 for(const route of ['whitepaper','whitepaper/agent']){assert.ok(metadata.includes(`'${route}'`));assert.ok(sitemap.includes(`/${route}`))}
 assert.ok(layout.includes("n.whitepaper,'/whitepaper'"));
 assert.ok(read('app/(localized)/[locale]/whitepaper/page.tsx').includes('readHumanWhitepaper'));
 assert.ok(read('app/(localized)/[locale]/whitepaper/agent/page.tsx').includes('readAgentWhitepaper'));
});
