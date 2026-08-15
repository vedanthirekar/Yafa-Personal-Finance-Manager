"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Nav } from "@/components/nav";
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

  React.useEffect(() => {
    if (!signedIn) router.replace("/login");
  }, [signedIn, router]);

  if (!signedIn) return null;

  return (
    <div className="min-h-screen">
      <Nav />
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
