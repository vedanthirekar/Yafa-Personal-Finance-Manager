"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

/**
 * All server state goes through TanStack Query -- there is no Redux/Zustand
 * store in this app, and there doesn't need to be. Nearly everything on screen
 * is server data, and Query already handles caching, refetching, and
 * invalidation for that. Local UI state stays in plain useState.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  // useState, not a module-level const: on the server a module-level client
  // would be shared across requests and leak one user's cached data into
  // another's response.
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: (failureCount, error) => {
              // Never retry auth failures -- the api client already tried a
              // refresh, so a 401 here means the session is genuinely gone.
              if (error instanceof Error && error.name === "ApiError") {
                const status = (error as { status?: number }).status;
                if (status === 401 || status === 403 || status === 404) return false;
              }
              return failureCount < 2;
            },
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
