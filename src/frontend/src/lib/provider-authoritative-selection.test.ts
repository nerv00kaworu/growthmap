import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const settings=fs.readFileSync(new URL("../components/Settings.tsx",import.meta.url),"utf8");
const panel=fs.readFileSync(new URL("../components/NodePanel/NodeAI.tsx",import.meta.url),"utf8");
const api=fs.readFileSync(new URL("./api.ts",import.meta.url),"utf8");
test("split save refreshes authoritative provider list before independent selection CAS",()=>{
 assert.match(api,/getProvider:\s*\(providerId: string\).*\/providers\/\$\{providerId\}/);
 assert.match(settings,/const rows=await loadProfiles\(providerId\)/);
 assert.match(settings,/await api\.setProviderSelection\(providerId,revision\)/);
 assert.match(settings,/selection_retry/);
 assert.doesNotMatch(settings,/saveLLMConfig\(/);
});
test("AI panel repairs only a same-profile stale revision and exposes generation cancellation",()=>{
 assert.match(panel,/llmConfig\.providerId===authoritative\.providerId&&llmConfig\.provider===authoritative\.providerType&&llmConfig\.model===authoritative\.model&&llmConfig\.revision!==authoritative\.revision/);
 assert.match(panel,/saveLLMConfig\(next\)/); assert.match(panel,/panel\.generationError/);
});
