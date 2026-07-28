"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, ImageIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ReviewBadge } from "@/components/review/ReviewBadge";
import type { SceneCard as SceneCardModel } from "@/lib/api/types";
import { cn, titleCase } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

function SceneCardBody({
  scene,
  selected,
  dragHandle,
}: {
  scene: SceneCardModel;
  selected?: boolean;
  dragHandle?: React.ReactNode;
}) {
  const selectScene = useUiStore((state) => state.selectScene);

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => selectScene(scene.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") selectScene(scene.id);
      }}
      className={cn(
        "flex flex-col overflow-hidden rounded-xl border bg-card text-left transition",
        selected
          ? "border-accent ring-2 ring-accent/30"
          : "border-border hover:border-accent/40",
      )}
    >
      <div className="relative">
        {scene.image?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={scene.image.url}
            alt={scene.title}
            className="aspect-video w-full object-cover"
          />
        ) : (
          <div className="flex aspect-video items-center justify-center bg-muted/50 text-muted-foreground">
            <ImageIcon className="h-6 w-6" />
          </div>
        )}
        <div className="absolute left-3 top-3 flex flex-wrap gap-2">
          <Badge className="bg-card/95 text-foreground">Scene {scene.id}</Badge>
          <Badge>{titleCase(scene.status)}</Badge>
        </div>
        {dragHandle}
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-display text-2xl leading-tight">{scene.title}</h3>
            <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
              {scene.goal || scene.description}
            </p>
          </div>
          <ReviewBadge
            score={scene.review_score ?? scene.review?.overall_score}
            approved={scene.review?.approved ?? true}
          />
        </div>

        <dl className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <div>
            <dt className="uppercase tracking-wide">Camera</dt>
            <dd className="mt-0.5 text-foreground">{scene.camera || "—"}</dd>
          </div>
          <div>
            <dt className="uppercase tracking-wide">Emotion</dt>
            <dd className="mt-0.5 text-foreground">{scene.emotion || "—"}</dd>
          </div>
          <div>
            <dt className="uppercase tracking-wide">Location</dt>
            <dd className="mt-0.5 text-foreground">{scene.location || "—"}</dd>
          </div>
          <div>
            <dt className="uppercase tracking-wide">v{scene.version}</dt>
            <dd className="mt-0.5 text-foreground">{scene.duration_seconds}s</dd>
          </div>
        </dl>
      </div>
    </article>
  );
}

export function SceneCard({
  scene,
  selected,
}: {
  scene: SceneCardModel;
  selected?: boolean;
}) {
  return <SceneCardBody scene={scene} selected={selected} />;
}

export function SortableSceneCard({
  scene,
  selected,
}: {
  scene: SceneCardModel;
  selected?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: scene.id });

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.85 : 1,
      }}
      className={cn(isDragging && "z-10")}
      {...attributes}
    >
      <SceneCardBody
        scene={scene}
        selected={selected}
        dragHandle={
          <button
            type="button"
            className="absolute right-3 top-3 rounded-md bg-card/95 p-1.5 text-muted-foreground hover:text-foreground"
            aria-label="Drag to reorder"
            onClick={(event) => event.stopPropagation()}
            {...listeners}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        }
      />
    </div>
  );
}
