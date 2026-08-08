"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/provider";
import { browserDownloadPort, copySecret, downloadSecret } from "./actions";
import { postPurchaseTranslate as tr, stateMessageKeys } from "./catalog";
import {
  ActivationKeyLoader, ALLOWED_ENTRIES, canRequestKey, ENTRY_ORDER, EntryHandlers,
  OperationFence, PublicPostPurchaseSnapshot, sanitizeCorrelationId, SecretClearLifecycle, subscribeDocumentHidden,
} from "./model";

export interface PostPurchasePanelProps {
  snapshot: PublicPostPurchaseSnapshot;
  /** Must eventually be implemented by an authenticated, no-store loader; this interface cannot enforce its internals. */
  keyLoader?: ActivationKeyLoader;
  entries?: EntryHandlers;
  clipboard?: { writeText(value: string): Promise<void> } | null;
  clearLifecycle?: SecretClearLifecycle;
}

export function PostPurchasePanel({ snapshot, keyLoader, entries = {}, clipboard, clearLifecycle = subscribeDocumentHidden }: PostPurchasePanelProps) {
  const { locale } = useI18n();
  const [secret, setSecret] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const fence = useRef<OperationFence | null>(null);
  const lifetime = useRef(0);
  if (!fence.current) fence.current = new OperationFence();
  const [titleKey, bodyKey] = stateMessageKeys(snapshot.state);
  const mayRequestKey = canRequestKey(snapshot) && Boolean(keyLoader);
  const correlationId = sanitizeCorrelationId(snapshot.correlationId);
  const clearSecret = useCallback(() => {
    fence.current?.invalidate();
    setSecret(null); setLoading(false); setNotice(null);
  }, []);

  useEffect(() => {
    const token = ++lifetime.current;
    fence.current?.mount();
    return () => { if (lifetime.current === token) { lifetime.current += 1; fence.current?.unmount(); } };
  }, []);
  useEffect(() => {
    const token = lifetime.current;
    const guardedClear = () => { if (token === lifetime.current && fence.current?.capture() !== null) clearSecret(); };
    const unsubscribe = clearLifecycle(guardedClear);
    return unsubscribe;
  }, [clearLifecycle, clearSecret]);
  useEffect(() => {
    clearSecret();
  }, [mayRequestKey, keyLoader, clearSecret]);

  const reveal = async () => {
    if (!mayRequestKey || loading || !keyLoader) return;
    const request = fence.current?.beginReveal();
    if (!request) return;
    setLoading(true); setNotice(null);
    try {
      const loaded = await keyLoader.load({ signal: request.signal });
      if (!fence.current?.isCurrent(request.generation)) return;
      if (typeof loaded !== "string" || loaded.length === 0) throw new Error("invalid response");
      setSecret(loaded); setLoading(false);
    } catch {
      if (!fence.current?.isCurrent(request.generation)) return;
      setSecret(null); setLoading(false); setNotice(tr(locale, "revealFallback"));
    }
  };
  const copyKey = async () => {
    if (!secret) return;
    const generation = fence.current?.capture();
    if (generation === null || generation === undefined) return;
    const port = clipboard === undefined ? navigator.clipboard : clipboard;
    const result = await copySecret(secret, port);
    if (fence.current?.isCurrent(generation)) setNotice(tr(locale, result === "ok" ? "copied" : "copyFallback"));
  };
  const downloadKey = () => {
    if (!secret) return;
    setNotice(tr(locale, downloadSecret(secret, browserDownloadPort()) === "ok" ? "downloaded" : "downloadFallback"));
  };

  return <section aria-labelledby="postpurchase-title">
    <h1 id="postpurchase-title">{tr(locale, "title")}</h1>
    <h2>{tr(locale, titleKey)}</h2><p>{tr(locale, bodyKey)}</p>
    {mayRequestKey ? <div>
      {loading
        ? <button type="button" onClick={clearSecret}>{tr(locale, "cancelReveal")}</button>
        : <button type="button" onClick={secret ? clearSecret : reveal}>{tr(locale, secret ? "hide" : "reveal")}</button>}
      {secret && <><output aria-live="polite">{secret}</output><p>{tr(locale, "backup")}</p>
        <button type="button" onClick={copyKey}>{tr(locale, "copyKey")}</button><button type="button" onClick={downloadKey}>{tr(locale, "downloadKey")}</button></>}
    </div> : <p>{tr(locale, "unavailableKey")}</p>}
    {notice && <p role="status">{notice}</p>}
    <div>{ENTRY_ORDER.filter((kind) => ALLOWED_ENTRIES[snapshot.state].includes(kind)).map((kind) => <div key={kind}>
      <button type="button" disabled={!entries[kind]} onClick={entries[kind]}>{tr(locale, kind)}</button>{!entries[kind] && <span> {tr(locale, "unavailable")}</span>}
    </div>)}</div>
    <p>{tr(locale, "correlation")}: <code>{correlationId ?? tr(locale, "correlationUnavailable")}</code></p>
    <button type="button" disabled={!correlationId} onClick={async () => { if (correlationId) { const generation = fence.current?.capture(); if (generation === null || generation === undefined) return; const result = await copySecret(correlationId, clipboard === undefined ? navigator.clipboard : clipboard); if (fence.current?.isCurrent(generation)) setNotice(tr(locale, result === "ok" ? "copied" : "copyFallback")); } }}>{tr(locale, "copyCorrelation")}</button>
  </section>;
}
