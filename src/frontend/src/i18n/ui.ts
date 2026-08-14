import type { Locale } from "./catalog";
export type Localized = Readonly<Record<Locale, string>>;
export const msg = (locale: Locale, value: Localized): string => value[locale];
export const dateLocale = (locale: Locale): string => locale;
/** Locale lookup for non-React UI boundaries (stores/conflict handlers). */
export function activeMsg(value: Localized): string {
  if (typeof window === "undefined") return value.en;
  let locale: Locale = "en";
  try { const stored = window.localStorage.getItem("growthmap.locale"); if (stored === "zh-TW" || stored === "zh-CN" || stored === "en") locale = stored; } catch { /* English fallback */ }
  return value[locale];
}
