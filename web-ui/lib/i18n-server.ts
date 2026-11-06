import "server-only";
import { cookies, headers } from "next/headers";
import { detectLocale } from "./i18n-core";
import { translator } from "./i18n-catalog";
export async function resolveLocale() {
  const [jar, incoming] = await Promise.all([cookies(), headers()]);
  return detectLocale(jar.get("emulytix_locale")?.value, incoming.get("accept-language") ?? "");
}
export async function serverT() { return translator(await resolveLocale()); }
