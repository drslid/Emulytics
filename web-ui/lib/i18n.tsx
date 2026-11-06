"use client";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { direction, normalizeLocale, type Locale, type Translate } from "./i18n-core";
import { translator } from "./i18n-catalog";
export type { Locale, Translate } from "./i18n-core";
const LocaleContext = createContext<{ locale: Locale; setLocale: (locale: Locale) => void; t: Translate } | null>(null);
export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  const router = useRouter();
  const setLocale = useCallback((next: Locale) => {
    document.cookie = `emulytix_locale=${next}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
    document.documentElement.lang = next;
    document.documentElement.dir = direction(next);
    router.refresh();
  }, [router]);
  const value = useMemo(() => ({ locale, setLocale, t: translator(locale) }), [locale, setLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}
export function useLocale() {
  const context = useContext(LocaleContext);
  if (!context) throw new Error("LocaleProvider is required");
  return context;
}
export function useT(): Translate { return useLocale().t; }
export function browserT(source: string, values?: Record<string, string | number>) {
  const language = typeof document === "undefined" ? "en" : document.documentElement.lang;
  return translator(normalizeLocale(language) ?? "en")(source, values);
}
