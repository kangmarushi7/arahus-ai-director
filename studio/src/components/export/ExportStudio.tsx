"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Radio, RefreshCw, Upload } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type {
  ExportFormat,
  ExportPresetId,
  ExportStudioState,
  PublishPlatform,
} from "@/lib/api/types";
import { titleCase } from "@/lib/utils";

const FORMATS: ExportFormat[] = ["mp4", "mov", "gif", "image_sequence"];
const PLATFORMS: PublishPlatform[] = ["youtube", "instagram", "tiktok", "x"];

export function ExportStudio({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [preset, setPreset] = useState<ExportPresetId>("youtube_shorts");
  const [format, setFormat] = useState<ExportFormat>("mp4");
  const [platform, setPlatform] = useState<PublishPlatform>("youtube");
  const [title, setTitle] = useState("");
  const [scheduleLater, setScheduleLater] = useState(false);
  const [scheduleAt, setScheduleAt] = useState("");

  const studioQuery = useQuery({
    queryKey: ["exports", projectId],
    queryFn: () => api.getExportStudio(projectId),
    refetchInterval: 4000,
  });
  const presetsQuery = useQuery({
    queryKey: ["export-presets"],
    queryFn: () => api.listExportPresets(),
  });
  const providersQuery = useQuery({
    queryKey: ["publish-providers"],
    queryFn: () => api.listPublishProviders(),
  });

  const setState = (state: ExportStudioState) => {
    queryClient.setQueryData(["exports", projectId], state);
  };

  const mutate = useMutation({
    mutationFn: async (action: () => Promise<ExportStudioState>) => action(),
    onSuccess: setState,
  });

  const studio = studioQuery.data;
  const readyJobs = useMemo(
    () => studio?.queue.filter((job) => job.status === "ready") ?? [],
    [studio],
  );
  const selectedReady = readyJobs[readyJobs.length - 1];

  if (studioQuery.isLoading && !studio) {
    return <p className="text-muted-foreground">Loading export studio…</p>;
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="font-display text-2xl">Export</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Stub encoder writes placeholder MP4/MOV/GIF/sequence + a project
          package. Swap the engine later without changing this queue API.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Preset</span>
            <select
              className="w-full rounded-md border border-border bg-background px-3 py-2"
              value={preset}
              onChange={(event) =>
                setPreset(event.target.value as ExportPresetId)
              }
            >
              {(presetsQuery.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label} ({item.aspect})
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Format</span>
            <select
              className="w-full rounded-md border border-border bg-background px-3 py-2"
              value={format}
              onChange={(event) =>
                setFormat(event.target.value as ExportFormat)
              }
            >
              {FORMATS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={mutate.isPending}
            onClick={() =>
              mutate.mutate(() =>
                api.enqueueExport(projectId, {
                  preset,
                  format,
                  process: true,
                }),
              )
            }
          >
            <Download className="h-3.5 w-3.5" />
            Queue & render
          </Button>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="font-display text-2xl">Render queue</h2>
        <div className="mt-4 space-y-3">
          {(studio?.queue ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No jobs yet.</p>
          ) : (
            [...(studio?.queue ?? [])].reverse().map((job) => (
              <div
                key={job.id}
                className="rounded-lg border border-border/80 bg-background/40 p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium">
                      {job.settings.preset} · {job.settings.format}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {job.settings.width}×{job.settings.height} ·{" "}
                      {job.settings.aspect} · attempt {job.attempt}
                    </p>
                  </div>
                  <Badge>{titleCase(job.status)}</Badge>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded bg-muted">
                  <div
                    className="h-full bg-accent transition-all"
                    style={{ width: `${Math.round(job.progress * 100)}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{job.message}</p>
                {job.output_path ? (
                  <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                    {job.output_path}
                  </p>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  {job.status === "queued" || job.status === "processing" ? (
                    <>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          mutate.mutate(() =>
                            api.exportJobAction(projectId, job.id, "pause"),
                          )
                        }
                      >
                        Pause
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          mutate.mutate(() =>
                            api.exportJobAction(projectId, job.id, "cancel"),
                          )
                        }
                      >
                        Cancel
                      </Button>
                    </>
                  ) : null}
                  {job.status === "paused" ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        mutate.mutate(() =>
                          api.exportJobAction(projectId, job.id, "resume"),
                        )
                      }
                    >
                      Resume
                    </Button>
                  ) : null}
                  {job.status === "failed" || job.status === "cancelled" ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        mutate.mutate(() =>
                          api.exportJobAction(projectId, job.id, "retry"),
                        )
                      }
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Retry
                    </Button>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="font-display text-2xl">Publish</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Abstract providers only — no OAuth. Stub returns fake URLs / schedules.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {(providersQuery.data ?? []).map((provider) => (
            <Badge key={provider.platform}>
              <Radio className="mr-1 h-3 w-3" />
              {provider.platform}
              {provider.oauth ? "" : " · stub"}
            </Badge>
          ))}
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">
              Platform
            </span>
            <select
              className="w-full rounded-md border border-border bg-background px-3 py-2"
              value={platform}
              onChange={(event) =>
                setPlatform(event.target.value as PublishPlatform)
              }
            >
              {PLATFORMS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-muted-foreground">Title</span>
            <input
              className="w-full rounded-md border border-border bg-background px-3 py-2"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Publish title"
            />
          </label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={scheduleLater}
            onChange={(event) => setScheduleLater(event.target.checked)}
          />
          Schedule later
        </label>
        {scheduleLater ? (
          <input
            type="datetime-local"
            className="mt-2 w-full max-w-sm rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={scheduleAt}
            onChange={(event) => setScheduleAt(event.target.value)}
          />
        ) : null}
        <div className="mt-4">
          <Button
            size="sm"
            disabled={!selectedReady || mutate.isPending}
            onClick={() => {
              if (!selectedReady) return;
              const iso =
                scheduleLater && scheduleAt
                  ? new Date(scheduleAt).toISOString()
                  : null;
              mutate.mutate(() =>
                api.publishExport(projectId, {
                  render_job_id: selectedReady.id,
                  platform,
                  title: title || undefined,
                  schedule_at: iso,
                  run: true,
                }),
              );
            }}
          >
            <Upload className="h-3.5 w-3.5" />
            {scheduleLater ? "Schedule publish" : "Publish now"}
          </Button>
          {!selectedReady ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Render a job to ready before publishing.
            </p>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              Using render {selectedReady.id}
            </p>
          )}
        </div>
        <div className="mt-4 space-y-2">
          {(studio?.publishes ?? []).slice().reverse().map((job) => (
            <div
              key={job.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/80 px-3 py-2 text-sm"
            >
              <div>
                <p>
                  {job.platform} · {job.title || "Untitled"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {job.external_url ||
                    job.schedule_at ||
                    job.error ||
                    job.status}
                </p>
              </div>
              <Badge>{titleCase(job.status)}</Badge>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="font-display text-2xl">Export history</h2>
        <div className="mt-4 space-y-2">
          {(studio?.history ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No versions yet.</p>
          ) : (
            [...(studio?.history ?? [])].reverse().map((entry) => (
              <div
                key={entry.id}
                className="rounded-lg border border-border/80 px-3 py-2 text-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium">
                    v{entry.version} · {entry.settings.preset} ·{" "}
                    {entry.settings.format}
                  </p>
                  {entry.publish_status ? (
                    <Badge>{titleCase(entry.publish_status)}</Badge>
                  ) : null}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{entry.message}</p>
                {entry.publish_url ? (
                  <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                    {entry.publish_url}
                  </p>
                ) : null}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
