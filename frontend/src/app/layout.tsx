import type { Metadata } from "next";
import { Montserrat, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const montserrat = Montserrat({
  variable: "--font-montserrat",
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "ATLAS AI — Nền tảng điều hành công việc bằng AI đa tác nhân",
  description: "Multi-Agent Mission Control & Closed-Loop Business Execution Platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" className={`${montserrat.variable} ${jetbrainsMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
