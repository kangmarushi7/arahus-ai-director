import { cn } from "@/lib/utils";

export function VideoPlayer({
  src,
  poster,
  className,
}: {
  src?: string | null;
  poster?: string | null;
  className?: string;
}) {
  if (!src) {
    return (
      <div
        className={cn(
          "flex aspect-video items-center justify-center rounded-lg border border-dashed border-border bg-muted/40 text-sm text-muted-foreground",
          className,
        )}
      >
        No video
      </div>
    );
  }

  return (
    <video
      className={cn(
        "aspect-video w-full rounded-lg border border-border bg-foreground/90 object-cover",
        className,
      )}
      controls
      playsInline
      poster={poster ?? undefined}
      src={src}
    />
  );
}
