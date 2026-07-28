"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function ImageViewer({
  src,
  alt,
  className,
}: {
  src?: string | null;
  alt: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  if (!src) {
    return (
      <div
        className={cn(
          "flex aspect-video items-center justify-center rounded-lg border border-dashed border-border bg-muted/40 text-sm text-muted-foreground",
          className,
        )}
      >
        No image
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "group relative block aspect-video w-full overflow-hidden rounded-lg border border-border bg-muted",
          className,
        )}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={alt}
          className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.02]"
        />
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/70 p-4">
          <div className="relative max-h-[90vh] max-w-5xl overflow-hidden rounded-xl bg-card">
            <Button
              size="icon"
              variant="secondary"
              className="absolute right-3 top-3 z-10"
              onClick={() => setOpen(false)}
            >
              <X className="h-4 w-4" />
            </Button>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={src}
              alt={alt}
              className="max-h-[90vh] w-full object-contain"
            />
          </div>
        </div>
      ) : null}
    </>
  );
}
