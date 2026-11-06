export const locales = ["en", "fr", "zh", "hi", "es", "pt", "ar", "ru", "bn", "de"] as const;
export type Locale = typeof locales[number];
export type Translate = (source: string, values?: Record<string, string | number>) => string;
export const localeInfo: Record<Locale, { name: string; flag: string; intl: string }> = {
  en: { name: "English", flag: "gb", intl: "en-GB" }, fr: { name: "Français", flag: "fr", intl: "fr-FR" },
  zh: { name: "中文", flag: "cn", intl: "zh-CN" }, hi: { name: "हिन्दी", flag: "in", intl: "hi-IN" },
  es: { name: "Español", flag: "es", intl: "es-ES" }, pt: { name: "Português", flag: "pt", intl: "pt-PT" },
  ar: { name: "العربية", flag: "sa", intl: "ar-SA" }, ru: { name: "Русский", flag: "ru", intl: "ru-RU" },
  bn: { name: "বাংলা", flag: "bd", intl: "bn-BD" }, de: { name: "Deutsch", flag: "de", intl: "de-DE" }
};
export function normalizeLocale(value: string | null | undefined): Locale | null {
  const base = value?.trim().toLowerCase().replaceAll("_", "-").split("-")[0];
  return locales.includes(base as Locale) ? base as Locale : null;
}
export function detectLocale(cookie?: string | null, acceptLanguage = ""): Locale {
  const selected = normalizeLocale(cookie);
  if (selected) return selected;
  const preferences = acceptLanguage.split(",").map((entry, order) => {
    const [tag, ...parameters] = entry.trim().split(";");
    const quality = parameters.find((parameter) => /^q=/i.test(parameter.trim()));
    const q = quality === undefined ? 1 : Number(quality.trim().slice(2));
    return { locale: normalizeLocale(tag), q, order };
  }).filter((entry) => entry.locale && Number.isFinite(entry.q) && entry.q > 0 && entry.q <= 1);
  preferences.sort((a, b) => b.q - a.q || a.order - b.order);
  return preferences[0]?.locale ?? "en";
}
export function interpolate(text: string, values: Record<string, string | number> = {}): string {
  return text.replace(/\{(\w+)\}/g, (match, key: string) => Object.hasOwn(values, key) ? String(values[key]) : match);
}
export function direction(locale: Locale): "ltr" | "rtl" { return locale === "ar" ? "rtl" : "ltr"; }

export function translateSource(catalog: Record<string, string>, source: string, values?: Record<string, string | number>): string {
  const translated = Object.hasOwn(catalog, source) ? catalog[source] : source;
  return interpolate(typeof translated === "string" ? translated : source, values);
}
export function formatDate(value: string, locale: Locale = "en", timeZone?: string): string {
  return new Intl.DateTimeFormat(localeInfo[locale].intl, {
    dateStyle: "short", timeStyle: "short", calendar: "gregory", ...(timeZone ? { timeZone } : {})
  }).format(new Date(value));
}
