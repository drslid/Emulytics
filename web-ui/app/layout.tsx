import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Emulytix",
  description: "Natural-language Android control workspace."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

