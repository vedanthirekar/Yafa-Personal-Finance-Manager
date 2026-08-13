"use client";

import { BarChart3, LogOut, Mic, Receipt } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/record", label: "Record", icon: Mic },
  { href: "/transactions", label: "Transactions", icon: Receipt },
  { href: "/insights", label: "Insights", icon: BarChart3 },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
        <Link href="/record" className="text-lg font-semibold tracking-tight">
          YAFA
        </Link>

        <nav className="flex flex-1 items-center gap-1">
          {LINKS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                pathname === href
                  ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                  : "text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>

        <button
          onClick={() => {
            api.logout();
            router.push("/login");
          }}
          className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    </header>
  );
}
