import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { catalogs } from "../i18n/catalog";
import { SSEParser } from "./sse-parser";

test("decoder handles split multibyte UTF-8 and EOF final flush", () => {
  const p = new SSEParser();
  const text = `event: canonical-change\ndata: {"schema":1,"kind":"graph","project_id":"p","revision":2,"cursor":"雪"}\n\n`;
  const bytes = new TextEncoder().encode(text); const cut = text.indexOf("雪");
  const before = new TextEncoder().encode(text.slice(0, cut + 1)).length - 1;
  const decoder = new TextDecoder();
  const first = decoder.decode(bytes.slice(0, before), { stream: true });
  const second = decoder.decode(bytes.slice(before), { stream: false });
  assert.equal(p.push(first).length, 0);
  assert.equal(p.push(second)[0]?.data.includes("雪"), true);
});

test("page source delegates live sync only to controller", () => {
  const source = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(source, /new LiveSyncController/);
  assert.doesNotMatch(source, /EventSource|SSEParser/);
});

test("external update notice and manual refresh are localized in all locales", () => {
  const values = (["zh-TW", "zh-CN", "en"] as const).map(locale => [catalogs[locale]["sync.external"], catalogs[locale]["sync.externalHelp"], catalogs[locale]["sync.refresh"]]);
  for (const row of values) for (const value of row) assert.ok(value.trim());
  assert.equal(new Set(values.map(row => row.join("|"))).size, 3);
});
