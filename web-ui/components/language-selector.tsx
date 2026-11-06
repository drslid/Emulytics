"use client";
import { useEffect, useId, useRef, useState } from "react";
import { useLocale } from "../lib/i18n";
import { locales, localeInfo } from "../lib/i18n-core";
export function LanguageSelector() {
  const { locale, setLocale, t } = useLocale();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) { if (!ref.current?.contains(event.target as Node)) setOpen(false); }
    function escape(event: KeyboardEvent) { if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); } }
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="language-selector" ref={ref}><button ref={trigger} type="button" className="language-trigger" aria-expanded={open} aria-controls={id} aria-label={`${t("Langue")} : ${localeInfo[locale].name}`} title={localeInfo[locale].name} onClick={() => setOpen(!open)}><img src={`/flags/${localeInfo[locale].flag}.svg`} alt="" width={22} height={16} /><span className="language-code">{locale.toUpperCase()}</span><span aria-hidden="true">⌄</span></button><div hidden={!open} className="language-options" id={id} aria-label={t("Langue")}>{locales.map((item) => <button type="button" key={item} lang={item} dir={item === "ar" ? "rtl" : "ltr"} aria-pressed={item === locale} onClick={() => { setLocale(item); setOpen(false); trigger.current?.focus(); }}><img src={`/flags/${localeInfo[item].flag}.svg`} alt="" width={22} height={16} /><span>{localeInfo[item].name}</span>{item === locale && <span className="language-selected" aria-hidden="true">✓</span>}</button>)}</div></div>;
}
export default LanguageSelector;
