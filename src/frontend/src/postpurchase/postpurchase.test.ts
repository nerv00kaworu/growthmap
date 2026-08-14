import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
(globalThis as typeof globalThis & { React: typeof React }).React = React;
import { I18nProvider } from "@/i18n/provider";
import { copySecret, downloadSecret } from "./actions";
import { POST_PURCHASE_STATES, postPurchaseTranslate, stateMessageKeys } from "./catalog";
import { ALLOWED_ENTRIES, canRequestKey, EphemeralSecret, ENTRY_ORDER, projectPublicPostPurchaseSnapshot, OperationFence, sanitizeCorrelationId } from "./model";
import { PostPurchasePanel } from "./PostPurchasePanel";

const locales = ["zh-TW", "zh-CN", "en"] as const;
const sentinel = "GM1.FLIGHT-SENTINEL-DO-NOT-SERIALIZE";

test("every state has deterministic title and guidance in all three locales", () => {
  for (const state of POST_PURCHASE_STATES) {
    const keys = stateMessageKeys(state);
    assert.equal(keys.length, 2);
    for (const locale of locales) for (const key of keys) assert.ok(postPurchaseTranslate(locale, key).trim(), `${locale}/${state}/${key}`);
  }
  assert.deepEqual(stateMessageKeys("refunded"), ["refundedTitle", "refundedBody"]);
  assert.deepEqual(stateMessageKeys("disputed"), ["disputedTitle", "disputedBody"]);
});
test("unknown locale falls back to English", () => assert.equal(postPurchaseTranslate("fr", "title"), postPurchaseTranslate("en", "title")));

test("pre-boundary projected props omit plaintext and loader is not invoked by rendering", () => {
  let loads = 0;
  const snapshot = projectPublicPostPurchaseSnapshot({ state: "success", keyAvailable: true, correlationId: "case_123" });
  const loader = { load: async ({ signal }: { signal: AbortSignal }) => { assert.equal(signal.aborted, false); loads += 1; return sentinel; } };
  const serialized = JSON.stringify({ snapshot }); // pre-boundary projection contract fixture; not a real Flight E2E
  const html = renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(PostPurchasePanel, { snapshot, keyLoader: loader })));
  assert.equal(loads, 0);
  assert.equal(serialized.includes(sentinel), false);
  assert.equal(html.includes(sentinel), false);
  assert.equal(/(?:href|src)=["'][^"']*(?:GM1|recovery|credential)/i.test(html), false);
});

test("strict projection rejects hostile spread and nested secret fields", () => {
  for (const input of [
    { state: "success", keyAvailable: true, activationKey: sentinel },
    { state: "success", keyAvailable: true, recoveryCredential: sentinel },
    { state: "success", keyAvailable: true, nested: { secret: sentinel } },
    { ...({ state: "success", keyAvailable: true } as Record<string, unknown>), activationKey: sentinel },
  ]) assert.throws(() => projectPublicPostPurchaseSnapshot(input), /unknown post-purchase snapshot field/);
  const projected = projectPublicPostPurchaseSnapshot({ state: "success", keyAvailable: true, correlationId: "case-9" });
  assert.deepEqual(Object.keys(projected).sort(), ["correlationId", "keyAvailable", "state"]);
  assert.equal(Object.isFrozen(projected), true);
  assert.equal(JSON.stringify(projected).includes(sentinel), false);
});

test("projection captures observable keys exactly once and has no reflection TOCTOU", () => {
  let ownKeyCalls = 0;
  const target = { state: "success", keyAvailable: true } as Record<string, unknown>;
  const changing = new Proxy(target, {
    ownKeys(inner) { ownKeyCalls += 1; if (ownKeyCalls > 1) inner.activationKey = sentinel; return Reflect.ownKeys(inner); },
  });
  const projected = projectPublicPostPurchaseSnapshot(changing);
  assert.equal(ownKeyCalls, 1);
  assert.equal(JSON.stringify(projected).includes(sentinel), false);
  const disappearing = new Proxy(target, { getOwnPropertyDescriptor(_inner, key) { if (key === "state") return undefined; return Reflect.getOwnPropertyDescriptor(target, key); } });
  assert.throws(() => projectPublicPostPurchaseSnapshot(disappearing), /descriptor/);
  const duplicateKeys = new Proxy(target, { ownKeys() { return ["state", "state", "keyAvailable"]; } });
  assert.throws(() => projectPublicPostPurchaseSnapshot(duplicateKeys), /uninspectable/);
});

test("projection rejects hidden, symbol, accessor, toJSON, and reflection-hostile inputs without invoking code", () => {
  const hidden = { state: "success", keyAvailable: true };
  Object.defineProperty(hidden, "activationKey", { value: sentinel, enumerable: false });
  assert.throws(() => projectPublicPostPurchaseSnapshot(hidden), /unknown/);
  assert.throws(() => projectPublicPostPurchaseSnapshot({ state: "success", keyAvailable: true, [Symbol("recoveryCredential")]: sentinel }), /unknown/);
  let getterCalls = 0;
  const accessor = { state: "success", keyAvailable: true };
  Object.defineProperty(accessor, "correlationId", { enumerable: true, get() { getterCalls += 1; throw new Error("must not run"); } });
  assert.throws(() => projectPublicPostPurchaseSnapshot(accessor), /descriptor/);
  assert.equal(getterCalls, 0);
  let jsonCalls = 0;
  const withToJSON = { state: "success", keyAvailable: true, toJSON() { jsonCalls += 1; return { activationKey: sentinel }; } };
  assert.throws(() => projectPublicPostPurchaseSnapshot(withToJSON), /unknown/);
  assert.equal(jsonCalls, 0);
  const ownKeysProxy = new Proxy({ state: "success", keyAvailable: true }, { ownKeys() { throw new Error("hostile proxy"); } });
  const descriptorProxy = new Proxy({ state: "success", keyAvailable: true }, { getOwnPropertyDescriptor() { throw new Error("hostile proxy"); } });
  assert.throws(() => projectPublicPostPurchaseSnapshot(ownKeysProxy), /uninspectable/);
  assert.throws(() => projectPublicPostPurchaseSnapshot(descriptorProxy), /uninspectable/);
});

test("retained lifecycle callback can be mounted-token guarded after unsubscribe/unmount", () => {
  const fence = new OperationFence(); fence.mount();
  let lifetime = 1; let setterCalls = 0;
  const token = lifetime;
  const retained = () => { if (token === lifetime && fence.capture() !== null) setterCalls += 1; };
  retained(); assert.equal(setterCalls, 1);
  lifetime += 1; fence.unmount();
  retained(); assert.equal(setterCalls, 1);
  fence.mount(); // Strict Mode replay creates a live fence, not a permanently disposed one
  assert.notEqual(fence.capture(), null);
});

test("generation fence rejects late resolution after hide, visibility clear, or unmount", async () => {
  for (const terminal of ["hide", "visibility", "unmount"] as const) {
    const fence = new OperationFence(); fence.mount();
    const request = fence.beginReveal(); assert.ok(request);
    let resolve!: (value: string) => void;
    const deferred = new Promise<string>((done) => { resolve = done; });
    let secret: string | null = null; let loading = true; let copies = 0; let downloads = 0;
    const lateCommit = deferred.then((value) => { if (fence.isCurrent(request.generation)) { secret = value; loading = false; } });
    if (terminal === "unmount") fence.unmount(); else fence.invalidate();
    secret = null; loading = false;
    assert.equal(request.signal.aborted, true);
    resolve(sentinel); await lateCommit;
    if (secret) { copies += 1; downloads += 1; }
    assert.deepEqual({ secret, loading, copies, downloads }, { secret: null, loading: false, copies: 0, downloads: 0 }, terminal);
  }
});

test("key request eligibility depends on projected state and availability", () => {
  for (const state of POST_PURCHASE_STATES) assert.equal(canRequestKey(projectPublicPostPurchaseSnapshot({ state, keyAvailable: true })), state === "success" || state === "recovered");
  assert.equal(canRequestKey(projectPublicPostPurchaseSnapshot({ state: "success", keyAvailable: false })), false);
});

test("ephemeral holder supports reveal-only acquisition and clears on hide, visibility, unmount, disabling copy/download", async () => {
  const holder = new EphemeralSecret();
  let loads = 0; let copies = 0; let downloads = 0;
  const loader = async () => { loads += 1; return sentinel; };
  const copy = async () => { const value = holder.get(); if (value) { copies += 1; await copySecret(value, { writeText: async () => undefined }); } };
  const download = () => { const value = holder.get(); if (value) { downloads += 1; downloadSecret(value, { createTextFile: () => "blob:safe", trigger: () => undefined, revoke: () => undefined }); } };
  assert.equal(loads, 0); await copy(); download(); assert.deepEqual([copies, downloads], [0, 0]);
  holder.set(await loader()); assert.equal(loads, 1); await copy(); download(); assert.deepEqual([copies, downloads], [1, 1]);
  holder.clear(); await copy(); download(); assert.deepEqual([copies, downloads], [1, 1]); // Hide
  holder.set(await loader()); holder.clear(); assert.equal(holder.get(), null); // visibility hidden lifecycle callback
  holder.set(await loader()); holder.dispose(); assert.equal(holder.get(), null); // unmount cleanup
});

test("all states render only permitted entries and absent handlers are disabled with truthful text", () => {
  for (const state of POST_PURCHASE_STATES) {
    const html = renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(PostPurchasePanel, { snapshot: projectPublicPostPurchaseSnapshot({ state, keyAvailable: false }) })));
    for (const kind of ENTRY_ORDER) {
      const label = postPurchaseTranslate("en", kind);
      assert.equal(html.includes(label), ALLOWED_ENTRIES[state].includes(kind), `${state}/${kind}`);
    }
    const disabledCount = (html.match(/disabled=""/g) ?? []).length;
    assert.equal(disabledCount, ALLOWED_ENTRIES[state].length + 1, state); // entries + unavailable correlation copy
    assert.equal((html.match(new RegExp(postPurchaseTranslate("en", "unavailable"), "g")) ?? []).length, ALLOWED_ENTRIES[state].length);
  }
});

test("clipboard and download failures have explicit deterministic fallback", async () => {
  assert.equal(await copySecret(sentinel, { writeText: async () => { throw new Error("denied"); } }), "fallback");
  assert.equal(await copySecret(sentinel, null), "fallback");
  const events: string[] = [];
  assert.equal(downloadSecret(sentinel, { createTextFile: (v) => { events.push(v); return "blob:safe"; }, trigger: () => undefined, revoke: (u) => events.push(u) }), "ok");
  assert.deepEqual(events, [`${sentinel}\n`, "blob:safe"]);
  assert.equal(downloadSecret(sentinel, null), "fallback");
});

test("correlation IDs are bounded and stripped rather than leaking sensitive context", () => {
  for (const value of ["case_123", "A.b-c_9", "x".repeat(64)]) assert.equal(sanitizeCorrelationId(value), value);
  for (const value of [undefined, "", " x ".repeat(40), "order@example.com", "abc/def", "abc?key=GM1.secret", "x".repeat(65), "換行\nsecret"]) assert.equal(sanitizeCorrelationId(value), null);
  assert.equal(sanitizeCorrelationId("  case-7  "), "case-7");
});

test("scoped source contracts forbid logs, initial plaintext props, and secret-to-navigation flows across whitespace", () => {
  const root = path.resolve(__dirname);
  const files = fs.readdirSync(root).filter((name) => /\.(ts|tsx)$/.test(name) && name !== "postpurchase.test.ts");
  const combined = files.map((name) => fs.readFileSync(path.join(root, name), "utf8")).join("\n");
  for (const name of files) {
    const source = fs.readFileSync(path.join(root, name), "utf8");
    if (name !== "catalog.ts") assert.equal(/[\u3400-\u9fff]/u.test(source), false, `${name}: bare CJK copy`);
  }
  assert.doesNotMatch(combined, /console\s*\.\s*(?:log|info|warn|error)\s*\(/);
  assert.doesNotMatch(combined, /snapshot\s*\.\s*activationKey/);
  assert.doesNotMatch(combined, /(?:href|src|location|searchParams|URLSearchParams)\s*[\s\S]{0,240}(?:secret|activationKey|recoveryCredential)/i);
});
