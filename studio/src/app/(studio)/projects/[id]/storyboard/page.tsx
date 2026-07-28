"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { AssetBrowser } from "@/components/assets/AssetBrowser";
import { ChatPanel } from "@/components/copilot/ChatPanel";
import { CostEstimatePanel } from "@/components/cost/CostEstimate";
import { SceneInspector } from "@/components/inspector/SceneInspector";
import { MediaPanel } from "@/components/media/MediaPanel";
import { ProgressPanel } from "@/components/progress/ProgressPanel";
import { ReviewBadge } from "@/components/review/ReviewBadge";
import { StoryboardCanvas } from "@/components/storyboard/StoryboardCanvas";
import { Button } from "@/components/ui/button";
import { useProjectProgress } from "@/hooks/use-project-progress";
import { api } from "@/lib/api/client";
import { mockCostEstimate } from "@/lib/mocks/data";
import { useUiStore } from "@/stores/ui-store";

export default function StoryboardPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const selectedSceneId = useUiStore((state) => state.selectedSceneId);
  const setActiveProjectId = useUiStore((state) => state.setActiveProjectId);

  useProjectProgress(projectId);

  useEffect(() => {
    setActiveProjectId(projectId);
  }, [projectId, setActiveProjectId]);

  const boardQuery = useQuery({
    queryKey: ["storyboard", projectId],
    queryFn: () => api.getStoryboard(projectId),
  });
  const estimateQuery = useQuery({
    queryKey: ["estimate", projectId, selectedSceneId ?? 1],
    queryFn: () => api.estimateSceneImage(projectId, selectedSceneId ?? 1),
    enabled: Boolean(selectedSceneId),
  });

  const board = boardQuery.data;
  const selected =
    board?.scenes.find((scene) => scene.id === selectedSceneId) ?? null;

  return (
    <div className="mx-auto max-w-[1400px] space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 px-0">
            <Link href={`/projects/${projectId}`}>
              <ArrowLeft className="h-4 w-4" />
              Back to project
            </Link>
          </Button>
          <p className="text-sm uppercase tracking-[0.2em] text-accent">
            Interactive studio
          </p>
          <h1 className="font-display text-4xl md:text-5xl">
            {board?.topic ?? "Loading…"}
          </h1>
          <div className="mt-3">
            <ReviewBadge
              score={board?.review?.overall_score}
              approved={board?.review?.approved}
            />
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <StoryboardCanvas
            projectId={projectId}
            scenes={board?.scenes ?? []}
          />
          <MediaPanel projectId={projectId} scene={selected} />
          <ChatPanel projectId={projectId} />
          <AssetBrowser projectId={projectId} embedded />
        </div>

        <aside className="space-y-4 xl:sticky xl:top-6 xl:self-start">
          <SceneInspector projectId={projectId} scene={selected} />
          <CostEstimatePanel
            estimate={estimateQuery.data ?? mockCostEstimate}
            title={
              selectedSceneId
                ? `Estimate · Scene ${selectedSceneId}`
                : "Pending generation"
            }
          />
          <ProgressPanel />
          {board?.review?.recommendations?.length ? (
            <section className="rounded-xl border border-border bg-card p-4">
              <h3 className="font-display text-xl">Review notes</h3>
              <ul className="mt-3 list-disc space-y-1 pl-4 text-sm text-muted-foreground">
                {board.review.recommendations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
