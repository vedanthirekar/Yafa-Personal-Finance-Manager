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
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = React.useState(false);

  React.useEffect(() => {
    // localStorage is unavailable during SSR, so the check runs after mount.
    if (!tokens.access) router.replace("/login");
    else setChecked(true);
  }, [router]);

  if (!checked) return null;

  return (
    <div className="min-h-screen">
      <Nav />
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
