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

/** The circular mint wordmark badge, reused by the sidebar and the login page. */
export function Logo({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "grid h-9 w-9 shrink-0 place-items-center rounded-full bg-mint-500 font-display text-lg font-semibold text-forest-950",
        className,
      )}
      aria-hidden
    >
      Y
    </span>
  );
}

/**
 * Desktop navigation: a deep-green rail pinned to the left edge.
 *
 * Split from the mobile bar below rather than made responsive, because the two
 * are genuinely different components -- one is a vertical labelled list on a
 * dark surface, the other a horizontal icon strip. Trying to express both with
 * the same markup produces class strings nobody can read.
 */
export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col bg-pine-900 px-4 py-6 lg:flex">
      <Link href="/record" className="mb-8 flex items-center gap-3 px-2">
        <Logo />
        <span className="font-display text-xl font-semibold text-cream-50">YAFA</span>
      </Link>

      <nav className="flex flex-1 flex-col gap-1">
        {LINKS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
              pathname === href
                ? "bg-pine-800 text-mint-400"
                : "text-cream-300/70 hover:bg-pine-800 hover:text-cream-50",
            )}
          >
            <Icon className="h-[18px] w-[18px]" />
            {label}
          </Link>
        ))}
      </nav>

      <button
        onClick={() => {
          api.logout();
          router.push("/login");
        }}
        className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-cream-300/60 transition-colors hover:bg-pine-800 hover:text-cream-50"
      >
        <LogOut className="h-[18px] w-[18px]" />
        Sign out
      </button>
    </aside>
  );
}

/** Mobile navigation: a bottom tab bar, plus a slim top bar for the wordmark. */
export function MobileNav() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <>
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-cream-300 bg-cream-100/90 px-4 backdrop-blur lg:hidden">
        <Link href="/record" className="flex items-center gap-2.5">
          <Logo className="h-7 w-7 text-base" />
          <span className="font-display text-lg font-semibold">YAFA</span>
        </Link>
        <button
          onClick={() => {
            api.logout();
            router.push("/login");
          }}
          className="text-ink-subtle"
          aria-label="Sign out"
        >
          <LogOut className="h-[18px] w-[18px]" />
        </button>
      </header>

      {/* `pb-[env(safe-area-inset-bottom)]` keeps the tabs clear of the iOS
          home indicator, which otherwise sits on top of the middle one. */}
      <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-cream-300 bg-cream-50 pb-[env(safe-area-inset-bottom)] lg:hidden">
        {LINKS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors",
              pathname === href ? "text-forest-700" : "text-ink-subtle",
            )}
          >
            <Icon className="h-5 w-5" />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
