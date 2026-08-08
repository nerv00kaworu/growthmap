import type { Metadata } from "next";
import "./globals.css";
import { I18nProvider } from "@/i18n/provider";

export const metadata: Metadata = {
  title: "GrowthMap",
  description: "專案思維生長系統",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-TW">
      <body><I18nProvider>{children}</I18nProvider></body>
    </html>
  );
}
