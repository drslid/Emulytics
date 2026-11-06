import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Emulytix · Tour de contrôle", template: "%s · Emulytix" },
  description: "La console pour piloter votre flotte de téléphones Android."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
