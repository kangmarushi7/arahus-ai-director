import { cn, titleCase } from "@/lib/utils";

export function ReviewBadge({
  score,
  approved,
  className,
}: {
  score?: number | null;
  approved?: boolean | null;
  className?: string;
}) {
  if (score == null) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground",
          className,
        )}
      >
        No review
      </span>
    );
  }

  const tone =
    approved === false || score < 85
      ? "border-danger/30 bg-danger/10 text-danger"
      : score >= 90
        ? "border-success/30 bg-success/10 text-success"
        : "border-warning/30 bg-warning/10 text-warning";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        tone,
        className,
      )}
    >
      <span className="font-display text-sm">{Math.round(score)}</span>
      <span>{approved ? "Approved" : titleCase("needs revision")}</span>
    </span>
  );
}
