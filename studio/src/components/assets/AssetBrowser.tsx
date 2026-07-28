"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Film, ImageIcon, MapPin, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ImageViewer } from "@/components/media/ImageViewer";
import { VideoPlayer } from "@/components/media/VideoPlayer";
import { api } from "@/lib/api/client";
import { cn, titleCase } from "@/lib/utils";

const TABS = [
  { id: "all", label: "All" },
  { id: "image", label: "Images" },
  { id: "video", label: "Videos" },
  { id: "character", label: "Characters" },
  { id: "world", label: "Worlds" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const icons = {
  character: UserRound,
  location: MapPin,
  style: MapPin,
  image: ImageIcon,
  video: Film,
};

function matchesTab(kind: string, tab: TabId): boolean {
  if (tab === "all") return true;
  if (tab === "world") return kind === "location" || kind === "style" || kind === "world";
  return kind === tab;
}

export function AssetBrowser({
  projectId,
  embedded = false,
}: {
  projectId?: string;
  embedded?: boolean;
}) {
  const [tab, setTab] = useState<TabId>("all");
  const assetsQuery = useQuery({
    queryKey: ["assets", projectId ?? "all"],
    queryFn: () => api.listAssets(projectId),
  });
  const filtered = useMemo(
    () => (assetsQuery.data ?? []).filter((asset) => matchesTab(asset.kind, tab)),
    [assetsQuery.data, tab],
  );

  return (
    <div className={cn("space-y-6", !embedded && "mx-auto max-w-6xl")}>
      {!embedded ? (
        <header>
          <p className="text-sm uppercase tracking-[0.2em] text-accent">
            Library
          </p>
          <h1 className="font-display text-5xl">Assets</h1>
          <p className="mt-2 max-w-2xl text-muted-foreground">
            Browse images, videos, characters, and worlds from the project
            registry.
          </p>
        </header>
      ) : (
        <div>
          <h3 className="font-display text-xl">Asset browser</h3>
          <p className="text-sm text-muted-foreground">
            Registry assets for this project
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {TABS.map((item) => (
          <Button
            key={item.id}
            size="sm"
            variant={tab === item.id ? "default" : "secondary"}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </div>

      {!filtered.length ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center text-muted-foreground">
          No assets in this category.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {filtered.map((asset) => {
            const Icon = icons[asset.kind as keyof typeof icons] ?? ImageIcon;
            const imageUrl =
              asset.kind === "image"
                ? asset.refs.url
                : asset.refs.url?.match(/\.(png|jpe?g|webp)/i)
                  ? asset.refs.url
                  : null;
            const videoUrl = asset.kind === "video" ? asset.refs.url : null;
            const worldLabel =
              asset.kind === "location" || asset.kind === "style"
                ? "World"
                : titleCase(asset.kind);

            return (
              <article
                key={`${asset.slug}-${asset.id}`}
                className="overflow-hidden rounded-xl border border-border bg-card"
              >
                {imageUrl ? (
                  <ImageViewer src={imageUrl} alt={asset.label} />
                ) : videoUrl ? (
                  <VideoPlayer src={videoUrl} />
                ) : (
                  <div className="flex aspect-[2/1] items-center justify-center bg-muted/40">
                    <Icon className="h-8 w-8 text-muted-foreground" />
                  </div>
                )}
                <div className="space-y-2 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="font-display text-2xl">{asset.label}</h2>
                    <Badge>
                      {worldLabel} #{asset.id}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{asset.slug}</p>
                  {typeof asset.metadata.appearance === "string" ? (
                    <p className="text-sm text-muted-foreground">
                      {asset.metadata.appearance}
                    </p>
                  ) : null}
                  {typeof asset.metadata.description === "string" ? (
                    <p className="text-sm text-muted-foreground">
                      {asset.metadata.description}
                    </p>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
