"use client";

import {
  DndContext,
  type DragEndEvent,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Copy,
  Pause,
  Play,
  Scissors,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type {
  ExportAspect,
  Timeline,
  TimelineClip,
  TimelineTrack,
  TransitionType,
} from "@/lib/api/types";
import { cn, titleCase } from "@/lib/utils";

const PPS = 28; // pixels per second
const TRANSITIONS: TransitionType[] = ["cut", "fade", "dissolve", "slide"];
const ASPECTS: ExportAspect[] = ["16:9", "9:16", "1:1"];

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const f = Math.floor((seconds % 1) * 10);
  return `${m}:${String(s).padStart(2, "0")}.${f}`;
}

function SortableClip({
  clip,
  selected,
  onSelect,
  onResize,
}: {
  clip: TimelineClip;
  selected: boolean;
  onSelect: () => void;
  onResize: (duration: number) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: clip.id });
  const width = Math.max(48, clip.duration_seconds * PPS);

  return (
    <div
      ref={setNodeRef}
      style={{
        width,
        transform: CSS.Transform.toString(transform),
        transition,
      }}
      className={cn(
        "relative h-full shrink-0 rounded-md border px-2 py-1 text-left text-xs",
        selected
          ? "border-accent bg-accent text-accent-foreground"
          : "border-border bg-card",
        isDragging && "z-10 opacity-90 shadow-md",
      )}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
      {...attributes}
      {...listeners}
    >
      <p className="truncate font-medium">{clip.label || clip.id}</p>
      <p className="truncate opacity-80">
        {formatTime(clip.duration_seconds)} · {titleCase(clip.transition_out)}
      </p>
      <div
        className="absolute bottom-0 right-0 top-0 w-2 cursor-ew-resize rounded-r-md bg-black/10"
        onPointerDown={(event) => {
          event.stopPropagation();
          event.preventDefault();
          const startX = event.clientX;
          const startDur = clip.duration_seconds;
          const onMove = (moveEvent: PointerEvent) => {
            const delta = (moveEvent.clientX - startX) / PPS;
            onResize(Math.max(0.5, startDur + delta));
          };
          const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
          };
          window.addEventListener("pointermove", onMove);
          window.addEventListener("pointerup", onUp);
        }}
      />
    </div>
  );
}

function TrackLane({
  track,
  selectedClipId,
  onSelectClip,
  onReorder,
  onResize,
}: {
  track: TimelineTrack;
  selectedClipId: string | null;
  onSelectClip: (id: string) => void;
  onReorder: (trackId: string, clipIds: string[]) => void;
  onResize: (clipId: string, duration: number) => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );
  const ids = track.clips.map((clip) => clip.id);

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    onReorder(track.id, arrayMove(ids, oldIndex, newIndex));
  }

  return (
    <div className="flex border-b border-border">
      <div className="flex w-28 shrink-0 items-center border-r border-border bg-muted/40 px-3 text-sm">
        {track.name}
      </div>
      <div
        className="relative flex-1 overflow-x-auto"
        style={{ minHeight: track.height }}
      >
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
        >
          <SortableContext items={ids} strategy={horizontalListSortingStrategy}>
            <div
              className="relative flex items-stretch gap-1 p-1"
              style={{ minWidth: Math.max(640, ids.length * 120) }}
            >
              {track.clips.map((clip) => (
                <SortableClip
                  key={clip.id}
                  clip={clip}
                  selected={selectedClipId === clip.id}
                  onSelect={() => onSelectClip(clip.id)}
                  onResize={(duration) => onResize(clip.id, duration)}
                />
              ))}
              {!track.clips.length ? (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  Empty {track.kind} track
                </p>
              ) : null}
            </div>
          </SortableContext>
        </DndContext>
      </div>
    </div>
  );
}

export function TimelineEditor({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [localPlayhead, setLocalPlayhead] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewPoster, setPreviewPoster] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const timelineQuery = useQuery({
    queryKey: ["timeline", projectId],
    queryFn: () => api.getTimeline(projectId),
  });

  const setTimeline = (timeline: Timeline) => {
    queryClient.setQueryData(["timeline", projectId], timeline);
    if (timeline.preview) {
      setPreviewUrl(timeline.preview.media_url ?? null);
      setPreviewPoster(timeline.preview.poster_url ?? null);
      setLocalPlayhead(timeline.preview.playhead_seconds);
    }
  };

  const syncMutation = useMutation({
    mutationFn: () => api.syncTimeline(projectId),
    onSuccess: setTimeline,
  });

  useEffect(() => {
    if (timelineQuery.isError || timelineQuery.data) return;
    // Auto-hydrate from storyboard when missing.
    syncMutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timelineQuery.isFetched]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setLocalPlayhead((value) => {
        const duration = timelineQuery.data?.duration_seconds ?? 0;
        const next = value + 0.1;
        return next >= duration ? 0 : next;
      });
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, timelineQuery.data?.duration_seconds]);

  useEffect(() => {
    const timeline = timelineQuery.data;
    if (!timeline) return;
    const video = timeline.tracks.find((track) => track.kind === "video");
    const clip = video?.clips.find(
      (item) =>
        item.start_seconds <= localPlayhead &&
        localPlayhead < item.start_seconds + item.duration_seconds,
    );
    setPreviewUrl(clip?.media_url ?? null);
    setPreviewPoster(clip?.poster_url ?? null);
  }, [localPlayhead, timelineQuery.data]);

  const mutate = useMutation({
    mutationFn: async (action: () => Promise<Timeline>) => action(),
    onSuccess: setTimeline,
  });

  const timeline = timelineQuery.data;
  const selectedClip = useMemo(() => {
    if (!timeline || !selectedClipId) return null;
    for (const track of timeline.tracks) {
      const clip = track.clips.find((item) => item.id === selectedClipId);
      if (clip) return clip;
    }
    return null;
  }, [timeline, selectedClipId]);

  const rulerMarks = useMemo(() => {
    const duration = timeline?.duration_seconds ?? 20;
    const marks: number[] = [];
    for (let t = 0; t <= duration + 1; t += 5) marks.push(t);
    return marks;
  }, [timeline?.duration_seconds]);

  if (timelineQuery.isLoading && !timeline) {
    return <p className="text-muted-foreground">Loading timeline…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
        >
          Sync from storyboard
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setPlaying((value) => !value)}
        >
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {playing ? "Pause" : "Play"}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={!selectedClip}
          onClick={() => {
            if (!selectedClip) return;
            mutate.mutate(() =>
              api.splitTimelineClip(
                projectId,
                selectedClip.id,
                localPlayhead,
              ),
            );
          }}
        >
          <Scissors className="h-3.5 w-3.5" />
          Split
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={!selectedClip}
          onClick={() => {
            if (!selectedClip) return;
            mutate.mutate(() =>
              api.duplicateTimelineClip(projectId, selectedClip.id),
            );
          }}
        >
          <Copy className="h-3.5 w-3.5" />
          Duplicate
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={!selectedClip}
          onClick={() => {
            if (!selectedClip) return;
            mutate.mutate(() =>
              api.deleteTimelineClip(projectId, selectedClip.id),
            );
            setSelectedClipId(null);
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </Button>
        <div className="flex flex-wrap gap-1">
          {TRANSITIONS.map((transition) => (
            <Button
              key={transition}
              size="sm"
              variant={
                selectedClip?.transition_out === transition
                  ? "default"
                  : "secondary"
              }
              disabled={!selectedClip}
              onClick={() => {
                if (!selectedClip) return;
                mutate.mutate(() =>
                  api.setTimelineTransition(
                    projectId,
                    selectedClip.id,
                    transition,
                  ),
                );
              }}
            >
              {titleCase(transition)}
            </Button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="flex border-b border-border text-xs text-muted-foreground">
            <div className="w-28 shrink-0 border-r border-border px-3 py-2">
              Tracks
            </div>
            <div className="relative flex-1 overflow-x-auto py-2">
              <div
                className="relative"
                style={{
                  width: Math.max(
                    640,
                    (timeline?.duration_seconds ?? 20) * PPS + 40,
                  ),
                }}
              >
                {rulerMarks.map((mark) => (
                  <span
                    key={mark}
                    className="absolute top-0"
                    style={{ left: mark * PPS }}
                  >
                    {formatTime(mark)}
                  </span>
                ))}
                <div
                  className="absolute bottom-[-2px] top-0 w-px bg-accent"
                  style={{ left: localPlayhead * PPS }}
                />
              </div>
            </div>
          </div>

          {(timeline?.tracks ?? []).map((track) => (
            <TrackLane
              key={track.id}
              track={track}
              selectedClipId={selectedClipId}
              onSelectClip={setSelectedClipId}
              onReorder={(trackId, clipIds) =>
                mutate.mutate(() =>
                  api.reorderTimeline(projectId, trackId, clipIds),
                )
              }
              onResize={(clipId, duration) =>
                mutate.mutate(() =>
                  api.resizeTimelineClip(projectId, clipId, duration),
                )
              }
            />
          ))}

          <div
            className="cursor-pointer border-t border-border px-3 py-2 text-sm text-muted-foreground"
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              // Approximate seek from click in the lower bar using full width.
              const ratio = Math.min(
                1,
                Math.max(0, (event.clientX - rect.left - 112) / (rect.width - 112)),
              );
              const seconds =
                ratio * (timeline?.duration_seconds ?? 0);
              setLocalPlayhead(seconds);
              mutate.mutate(() => api.seekTimeline(projectId, seconds));
            }}
          >
            Playhead {formatTime(localPlayhead)} /{" "}
            {formatTime(timeline?.duration_seconds ?? 0)}
          </div>
        </section>

        <aside className="space-y-4">
          <section className="rounded-xl border border-border bg-card p-4">
            <h3 className="font-display text-xl">Live preview</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Frame seek uses existing assets only — no regeneration.
            </p>
            <div className="mt-3 overflow-hidden rounded-lg bg-muted/40">
              {previewUrl?.match(/\.(mp4|webm|mov)(\?|$)/i) ? (
                <video
                  ref={videoRef}
                  key={previewUrl}
                  src={previewUrl}
                  poster={previewPoster ?? undefined}
                  className="aspect-video w-full object-cover"
                  controls
                />
              ) : previewPoster || previewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={previewPoster || previewUrl || ""}
                  alt="Timeline preview"
                  className="aspect-video w-full object-cover"
                />
              ) : (
                <div className="flex aspect-video items-center justify-center text-sm text-muted-foreground">
                  No media under playhead
                </div>
              )}
            </div>
            {selectedClip ? (
              <dl className="mt-3 space-y-1 text-xs text-muted-foreground">
                <div className="flex justify-between gap-2">
                  <dt>Clip</dt>
                  <dd className="text-foreground">{selectedClip.label}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>In / Out</dt>
                  <dd className="text-foreground">
                    {selectedClip.in_point.toFixed(1)}s →{" "}
                    {selectedClip.out_point.toFixed(1)}s
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>Transition</dt>
                  <dd className="text-foreground">
                    {titleCase(selectedClip.transition_out)}
                  </dd>
                </div>
              </dl>
            ) : null}
          </section>

          <section className="rounded-xl border border-border bg-card p-4">
            <h3 className="font-display text-xl">Export queue</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Queue MP4 renders for common aspect ratios.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {ASPECTS.map((aspect) => (
                <Button
                  key={aspect}
                  size="sm"
                  onClick={() =>
                    mutate.mutate(() =>
                      api.enqueueTimelineExport(projectId, aspect),
                    )
                  }
                >
                  MP4 · {aspect}
                </Button>
              ))}
            </div>
            <ul className="mt-4 space-y-2">
              {(timeline?.export_queue ?? []).length ? (
                timeline?.export_queue.map((job) => (
                  <li
                    key={job.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-sm"
                  >
                    <span>
                      {job.format.toUpperCase()} · {job.aspect}
                    </span>
                    <Badge>{titleCase(job.status)}</Badge>
                  </li>
                ))
              ) : (
                <li className="text-sm text-muted-foreground">Queue is empty</li>
              )}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
