"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api/client";
import { titleCase } from "@/lib/utils";

export default function SettingsPage() {
  const statusQuery = useQuery({
    queryKey: ["api-status"],
    queryFn: () => api.getStatus(),
  });

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "(not set — using mocks)";
  const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS ?? "auto";

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header>
        <p className="text-sm uppercase tracking-[0.2em] text-accent">Settings</p>
        <h1 className="font-display text-5xl">Studio settings</h1>
        <p className="mt-2 text-muted-foreground">
          Authentication is not enabled in Sprint 6.1. Configure the FastAPI
          base URL to switch from mocks to live data.
        </p>
      </header>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="font-display text-2xl">Connection</h2>
        <dl className="mt-4 space-y-3 text-sm">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">API URL</dt>
            <dd className="font-mono text-xs">{apiUrl}</dd>
          </div>
          <Separator />
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Mock mode</dt>
            <dd>
              <Badge>{api.usingMocks() ? "on" : "off"} ({useMocks})</Badge>
            </dd>
          </div>
        </dl>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="font-display text-2xl">Service readiness</h2>
        <ul className="mt-4 space-y-2">
          {Object.entries(statusQuery.data ?? {}).map(([key, value]) => (
            <li
              key={key}
              className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-sm"
            >
              <span>{titleCase(key)}</span>
              <Badge
                className={
                  value
                    ? "border-success/30 bg-success/10 text-success"
                    : undefined
                }
              >
                {value ? "ready" : "unavailable"}
              </Badge>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        <h2 className="font-display text-2xl text-foreground">Env vars</h2>
        <pre className="mt-3 overflow-x-auto rounded-lg bg-background p-3 text-xs">
{`NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_USE_MOCKS=false`}
        </pre>
      </section>
    </div>
  );
}
