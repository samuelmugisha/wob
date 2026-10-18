import type { Metadata } from "next";
import { Inter, Libre_Baskerville } from "next/font/google";
import AppShell from "@/components/AppShell";
import "./globals.css";

const serif = Libre_Baskerville({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-serif" });
const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Women on Boards Awards",
  description: "AI-powered evaluation and ranking system for the Women on Boards Awards 2026",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable}`}>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
