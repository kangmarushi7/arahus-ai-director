import { formatDuration, formatUsd } from "@/lib/utils";
import type { CostEstimate } from "@/lib/api/types";

export function CostEstimatePanel({
  estimate,
  title = "Cost estimate",
}: {
  estimate: CostEstimate;
  title?: string;
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h3 className="font-display text-xl text-foreground">{title}</h3>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-muted-foreground">Images</dt>
          <dd className="text-lg font-medium">{estimate.image_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Videos</dt>
          <dd className="text-lg font-medium">{estimate.video_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">GPU time</dt>
          <dd className="text-lg font-medium">
            {formatDuration(estimate.estimated_gpu_seconds)}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Est. cost</dt>
          <dd className="text-lg font-medium text-accent">
            {formatUsd(estimate.estimated_cost_usd)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
