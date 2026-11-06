import "./globals.css";
import "./locale.css";
import "./screens.css";
import "./usermanagement.css";
import "./monitoring.css";
import "./architecture-map.css";
import "./execution-gallery.css";
import "./workflow-editor.css";
import "./responsive.css";
import "./mobile-navigation.css";
import "./dashboard-charts.css";
import "./emulators.css";
import "./tailwind.css";
import { LocaleProvider } from "../lib/i18n";
import { resolveLocale, serverT } from "../lib/i18n-server";
import { direction } from "../lib/i18n-core";
import type { Metadata, Viewport } from "next";

export async function generateMetadata(): Promise<Metadata> {
  const t = await serverT();
  return {
  title: { default: `Emulytix · ${t("Tableau de bord")}`, template: "%s · Emulytix" },
  applicationName: "Emulytix",
  description: t("Votre tour de contrôle pour piloter et automatiser votre flotte d’appareils mobiles."),
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/favicon.ico?v=brand-1", type: "image/x-icon", sizes: "16x16 32x32 48x48" },
      { url: "/icons/favicon-16.png", type: "image/png", sizes: "16x16" },
      { url: "/icons/favicon-32.png", type: "image/png", sizes: "32x32" }
    ],
    apple: [{ url: "/apple-touch-icon.png", type: "image/png", sizes: "180x180" }]
  }
  };
}

export const viewport: Viewport = { themeColor: "#f8fafd", colorScheme: "light" };

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const locale = await resolveLocale();
  return <html lang={locale} dir={direction(locale)}><body><LocaleProvider locale={locale}>{children}</LocaleProvider></body></html>;
}
