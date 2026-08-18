import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const settings=fs.readFileSync(new URL("../components/Settings.tsx",import.meta.url),"utf8");
const panel=fs.readFileSync(new URL("../components/NodePanel/NodeAI.tsx",import.meta.url),"utf8");
const api=fs.readFileSync(new URL("./api.ts",import.meta.url),"utf8");

test("secret save persists the post-secret authoritative provider revision",()=>{
  assert.match(api,/getProvider:\s*\(providerId: string\).*\/providers\/\$\{providerId\}/);
  assert.match(settings,/const authoritative = apiKey\.trim\(\).*await api\.getProvider\(saved\.id\) : saved/);
  assert.match(settings,/revision: authoritative\.revision/);
  assert.doesNotMatch(settings,/saveLLMConfig\(\{[^}]*revision: saved\.revision/);
});

test("AI panel repairs only a same-profile stale revision and exposes generation cancellation",()=>{
  assert.match(panel,/llmConfig\.providerId===authoritative\.providerId&&llmConfig\.provider===authoritative\.providerType&&llmConfig\.model===authoritative\.model&&llmConfig\.revision!==authoritative\.revision/);
  assert.match(panel,/saveLLMConfig\(next\)/);
  assert.match(panel,/panel\.generationError/);
});
