"use client";

import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

function formatEta(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds <= 0) return "Done";
  if (seconds < 60) return `~${seconds}s`;
  return `~${Math.ceil(seconds / 60)}m`;
}

export function ProgressPanel({ className }: { className?: string }) {
  const {
    progressOpen,
    progressFraction,
    progressMessage,
    progressStages,
    currentStage,
    etaSeconds,
    costUsd,
    gpuUsage,
    setProgressOpen,
  } = useUiStore();

  if (!progressOpen) return null;

  const stages = Object.entries(progressStages);

  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-card p-4 shadow-sm",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-xl">Live progress</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {progressMessage || "Waiting for pipeline events…"}
          </p>
        </div>
        <button
          type="button"
          className="text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setProgressOpen(false)}
        >
          Hide
        </button>
      </div>

      <Progress className="mt-4" value={Math.round(progressFraction * 100)} />
      <p className="mt-2 text-xs text-muted-foreground">
        {Math.round(progressFraction * 100)}%
      </p>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-lg bg-muted/40 p-3">
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            Stage
          </dt>
          <dd className="mt-1 font-medium">{currentStage || "Idle"}</dd>
        </div>
        <div className="rounded-lg bg-muted/40 p-3">
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            ETA
          </dt>
          <dd className="mt-1 font-medium">{formatEta(etaSeconds)}</dd>
        </div>
        <div className="rounded-lg bg-muted/40 p-3">
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            Cost
          </dt>
          <dd className="mt-1 font-medium">
            {costUsd != null ? `$${costUsd.toFixed(2)}` : "—"}
          </dd>
        </div>
        <div className="rounded-lg bg-muted/40 p-3">
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            GPU
          </dt>
          <dd className="mt-1 font-medium">
            {gpuUsage != null ? `${Math.round(gpuUsage * 100)}%` : "—"}
          </dd>
        </div>
      </dl>

      {gpuUsage != null ? (
        <div className="mt-3">
          <p className="mb-1 text-xs text-muted-foreground">GPU usage</p>
          <Progress value={Math.round(gpuUsage * 100)} />
        </div>
      ) : null}

      {stages.length ? (
        <ul className="mt-4 space-y-2">
          {stages.map(([name, value]) => (
            <li key={name} className="text-sm">
              <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                <span>{name}</span>
                <span>{Math.round(value * 100)}%</span>
              </div>
              <Progress value={Math.round(value * 100)} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
