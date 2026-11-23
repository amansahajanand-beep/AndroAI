"use client";

import { useState } from "react";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/overlays";
import { isUnauthorized } from "@/lib/api/errors";
import { qk, shouldRetry } from "@/lib/api/hooks";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => {
    const qc: QueryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: shouldRetry, staleTime: 20_000, refetchOnWindowFocus: false },
        mutations: { retry: false },
      },
      queryCache: new QueryCache({
        onError: (error, query) => {
          // A 401 anywhere means the session expired: let AuthGuard redirect.
          if (isUnauthorized(error) && query.queryKey[0] !== qk.session[0]) {
            qc.invalidateQueries({ queryKey: qk.session });
          }
        },
      }),
      mutationCache: new MutationCache({
        onError: (error) => {
          if (isUnauthorized(error)) qc.invalidateQueries({ queryKey: qk.session });
        },
      }),
    });
    return qc;
  });

  return (
    <QueryClientProvider client={client}>
      <ThemeProvider attribute="class" defaultTheme="light" themes={["dark", "light"]} enableSystem disableTransitionOnChange>
        <TooltipProvider delayDuration={400}>
          {children}
          <Toaster
            position="bottom-right"
            toastOptions={{
              classNames: {
                toast: "!bg-popover !text-popover-foreground !border-border-strong !rounded-xl !shadow-pop !text-[14px] !font-sans",
                description: "!text-muted-foreground",
              },
            }}
          />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
