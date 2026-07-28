"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ImageIcon, RefreshCw, Sparkles } from "lucide-react";

import { ImageViewer } from "@/components/media/ImageViewer";
import { VideoPlayer } from "@/components/media/VideoPlayer";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api/client";
import type { SceneCard, SceneVersion } from "@/lib/api/types";
import { cn, titleCase } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

export function MediaPanel({
  projectId,
  scene,
}: {
  projectId: string;
  scene: SceneCard | null;
}) {
  const queryClient = useQueryClient();
  const compareVersion = useUiStore((state) => state.compareVersion);
  const setCompareVersion = useUiStore((state) => state.setCompareVersion);
  const setProgress = useUiStore((state) => state.setProgress);

  const imageMutation = useMutation({
    mutationFn: () => {
      if (!scene) throw new Error("No scene");
      return api.generateSceneImage(projectId, scene.id);
    },
    onMutate: () => {
      setProgress({
        fraction: 0.15,
        message: `Generating image for scene ${scene?.id}…`,
        currentStage: "Images",
        stages: { Images: 0.2 },
        etaSeconds: 45,
        gpuUsage: 0.35,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storyboard", projectId] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      setProgress({
        fraction: 1,
        message: "Image ready",
        currentStage: "Images",
        stages: { Images: 1 },
        etaSeconds: 0,
        gpuUsage: 0.1,
      });
    },
  });

  const videoMutation = useMutation({
    mutationFn: () => {
      if (!scene) throw new Error("No scene");
      return api.generateSceneVideo(projectId, scene.id);
    },
    onMutate: () => {
      setProgress({
        fraction: 0.2,
        message: `Generating video for scene ${scene?.id}…`,
        currentStage: "Videos",
        stages: { Videos: 0.25 },
        etaSeconds: 90,
        gpuUsage: 0.55,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storyboard", projectId] });
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      setProgress({
        fraction: 1,
        message: "Video ready",
        currentStage: "Videos",
        stages: { Videos: 1 },
        etaSeconds: 0,
        gpuUsage: 0.15,
      });
    },
  });

  if (!scene) {
    return (
      <section className="rounded-xl border border-border bg-card p-4">
        <h3 className="font-display text-xl">Media panel</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Select a scene to preview, generate, or compare versions.
        </p>
      </section>
    );
  }

  const versions = [...(scene.versions ?? [])].sort(
    (a, b) => b.version - a.version,
  );
  const compared: SceneVersion | undefined = versions.find(
    (version) => version.version === compareVersion,
  );

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-xl">Media panel</h3>
          <p className="text-sm text-muted-foreground">
            Scene {scene.id} · v{scene.version}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={() => imageMutation.mutate()}
            disabled={imageMutation.isPending}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {scene.image?.url ? "Regenerate" : "Generate"} image
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => videoMutation.mutate()}
            disabled={videoMutation.isPending}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {scene.video?.url ? "Regenerate" : "Generate"} video
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            Image preview
          </p>
          {scene.image?.url ? (
            <ImageViewer src={scene.image.url} alt={scene.title} />
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-lg bg-muted/50 text-muted-foreground">
              <ImageIcon className="h-6 w-6" />
            </div>
          )}
        </div>

        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            Video preview
          </p>
          {scene.video?.url ? (
            <VideoPlayer src={scene.video.url} poster={scene.image?.url} />
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
              No video yet
            </div>
          )}
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Compare versions
          </p>
          {compareVersion != null ? (
            <button
              type="button"
              className="text-xs text-accent hover:underline"
              onClick={() => setCompareVersion(null)}
            >
              Clear
            </button>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge className="bg-accent text-accent-foreground">
            Current v{scene.version}
          </Badge>
          {versions.map((version) => (
            <button
              key={version.version}
              type="button"
              onClick={() => setCompareVersion(version.version)}
              className={cn(
                "rounded-md border px-2 py-1 text-xs transition",
                compareVersion === version.version
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-border hover:border-accent/50",
              )}
            >
              v{version.version} · {titleCase(version.status)}
            </button>
          ))}
        </div>

        {compared ? (
          <div className="mt-3 grid gap-3 rounded-lg border border-border bg-background p-3 text-sm md:grid-cols-2">
            <div>
              <p className="text-xs uppercase text-muted-foreground">Current</p>
              <p className="mt-1 font-medium">{scene.camera || "—"}</p>
              <p className="mt-1 text-muted-foreground">{scene.emotion}</p>
              <p className="mt-2 line-clamp-4 text-xs">{scene.image_prompt}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-muted-foreground">
                v{compared.version}
                {compared.change_summary
                  ? ` · ${compared.change_summary}`
                  : ""}
              </p>
              <p className="mt-1 font-medium">{compared.camera || "—"}</p>
              <p className="mt-1 text-muted-foreground">{compared.emotion}</p>
              <p className="mt-2 line-clamp-4 text-xs">{compared.image_prompt}</p>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
