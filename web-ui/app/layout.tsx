import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: { default: "Emulytix · Tour de contrôle", template: "%s · Emulytix" },
  applicationName: "Emulytix",
  description: "Votre tour de contrôle pour piloter et automatiser votre flotte d’appareils mobiles.",
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

export const viewport: Viewport = { themeColor: "#f8fafd", colorScheme: "light" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
