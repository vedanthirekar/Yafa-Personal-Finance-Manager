"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { MobileNav, Sidebar } from "@/components/nav";
import { tokens } from "@/lib/api";

/**
 * Client-side auth gate for every page under (app).
 *
 * This is a UX guard, not a security boundary -- it stops a signed-out visitor
 * seeing an empty shell flash. The real enforcement is the API rejecting any
 * request without a valid bearer token.
 */
/** Never fires: the token can't change without a full page load, since signing
 *  out navigates via `window.location`. Required by useSyncExternalStore. */
const subscribe = () => () => {};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  /**
   * `tokens.access` reads localStorage, which doesn't exist during SSR.
   * useSyncExternalStore is the sanctioned way to read a client-only value:
   * the third argument is the server snapshot, so both the server render and
   * the hydration render see `false` and emit nothing, and only the render
   * after hydration consults localStorage. Doing this with an effect and
   * setState instead causes a cascading re-render on every mount.
   */
  const signedIn = React.useSyncExternalStore(
    subscribe,
    () => Boolean(tokens.access),
    () => false,
  );

  /**
   * Read the token again here rather than depending on `signedIn`.
   *
   * On a hard page load `signedIn` is `false` for the hydration render -- that
   * is the whole point of the server snapshot -- and effects fire with the
   * values from the render that committed. Depending on it would redirect a
   * perfectly signed-in user to /login on every refresh, before the
   * post-hydration re-render ever gets to say otherwise. Inside an effect we
   * are unambiguously on the client, so localStorage can just be asked.
   */
  React.useEffect(() => {
    if (!tokens.access) router.replace("/login");
  }, [router]);

  if (!signedIn) return null;

  return (
    <div className="min-h-screen">
      <Sidebar />
      <MobileNav />
      {/* Two nested boxes on purpose. The outer one reserves the 15rem the
          fixed sidebar occupies; the inner one centres the content in what's
          left. Doing both on one element would centre against the full
          viewport and then shove the result right, off-centre. `pb-24` clears
          the fixed mobile tab bar, which otherwise covers the last row. */}
      <div className="lg:pl-60">
        <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 lg:px-10 lg:pb-14 lg:pt-10">
          {children}
        </main>
      </div>
    </div>
  );
}
