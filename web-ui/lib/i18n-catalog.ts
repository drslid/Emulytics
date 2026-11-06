import en from "./locales/en.json";
import fr from "./locales/fr.json";
import zh from "./locales/zh.json";
import hi from "./locales/hi.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import ar from "./locales/ar.json";
import ru from "./locales/ru.json";
import bn from "./locales/bn.json";
import de from "./locales/de.json";
import { translateSource, type Locale, type Translate } from "./i18n-core";
export const catalogs: Record<Locale, Record<string, string>> = { en, fr, zh, hi, es, pt, ar, ru, bn, de };
export function translator(locale: Locale): Translate {
  return (source, values) => translateSource(catalogs[locale], source, values);
}
