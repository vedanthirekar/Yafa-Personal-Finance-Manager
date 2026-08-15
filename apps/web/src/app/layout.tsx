import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import "./globals.css";

import { Providers } from "@/components/providers";

/**
 * Two families, two jobs.
 *
 * Inter is the interface: labels, tables, numbers. Fraunces is the voice:
 * page titles, headline figures, the marketing hero. Both are variable fonts,
 * so a single file covers every weight -- asking for `weight: "400"` would
 * download a static instance and lose the range.
 *
 * `next/font` self-hosts these at build time. Nothing is fetched from Google
 * at runtime, so there is no third-party request and no swap-in flash.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  // Fraunces ships knobs for softness and "wonk" (its quirkier alternates).
  // Dialled down: this is a finance app, not a jam label.
  axes: ["SOFT", "WONK", "opsz"],
});

export const metadata: Metadata = {
  title: "YAFA - AI Expense Tracker",
  description:
    "Voice-driven expense capture with semantic categorization and spend forecasting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${fraunces.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-cream-100 font-sans text-ink antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
