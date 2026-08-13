import type { Metadata } from "next";
import "./globals.css";

import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "YAFA — AI Expense Tracker",
  description:
    "Voice-driven expense capture with semantic categorization and spend forecasting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
