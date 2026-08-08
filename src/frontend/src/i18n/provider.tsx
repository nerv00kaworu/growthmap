"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { DEFAULT_LOCALE, Locale, MessageKey, SUPPORTED_LOCALES, Translate, resolveLocale, translate } from "./catalog";

export const LOCALE_STORAGE_KEY = "growthmap.locale";
export type StorageLike = Pick<Storage, "getItem" | "setItem">;
export type StorageHost = { readonly localStorage: StorageLike };

export function getLocalStorage(host: StorageHost | null | undefined): StorageLike | null {
  if (!host) return null;
  try { return host.localStorage; }
  catch { return null; }
}

export function readStoredLocale(storage: StorageLike | null | undefined): Locale {
  if (!storage) return DEFAULT_LOCALE;
  try { return resolveLocale(storage.getItem(LOCALE_STORAGE_KEY)); }
  catch { return DEFAULT_LOCALE; }
}
export function persistLocale(storage: StorageLike | null | undefined, locale: Locale): boolean {
  if (!storage) return false;
  try { storage.setItem(LOCALE_STORAGE_KEY, locale); return true; }
  catch { return false; }
}

interface I18nValue { locale: Locale; setLocale(locale: Locale): void; t: Translate }
const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  useEffect(() => { setLocaleState(readStoredLocale(getLocalStorage(window))); }, []);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const setLocale = useCallback((next: Locale) => { setLocaleState(next); persistLocale(getLocalStorage(window), next); }, []);
  const t = useCallback<Translate>((key, values) => translate(locale, key, values), [locale]);
  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}

export function LocaleSelector() {
  const { locale, setLocale, t } = useI18n();
  return <select aria-label={t("locale.label")} value={locale} onChange={(event) => setLocale(resolveLocale(event.target.value))}
    className="surface-subtle rounded-md px-2 py-1.5 text-xs text-[var(--text-primary)] border border-gray-700/60">
    {SUPPORTED_LOCALES.map((item) => <option key={item} value={item}>{t(`locale.${item}` as MessageKey)}</option>)}
  </select>;
}
