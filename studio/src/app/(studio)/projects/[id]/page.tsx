"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Clapperboard, ListVideo, Mic2, Play, Sparkles, Upload } from "lucide-react";

import { CostEstimatePanel } from "@/components/cost/CostEstimate";
import { ProgressPanel } from "@/components/progress/ProgressPanel";
import { ReviewBadge } from "@/components/review/ReviewBadge";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useProjectProgress } from "@/hooks/use-project-progress";
import { api } from "@/lib/api/client";
import { mockCostEstimate } from "@/lib/mocks/data";
import { titleCase } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const setProgress = useUiStore((state) => state.setProgress);
  const setActiveProjectId = useUiStore((state) => state.setActiveProjectId);

  useProjectProgress(projectId);

  useEffect(() => {
    setActiveProjectId(projectId);
  }, [projectId, setActiveProjectId]);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });
  const storyboardQuery = useQuery({
    queryKey: ["storyboard", projectId],
    queryFn: () => api.getStoryboard(projectId),
  });

  const generateMutation = useMutation({
    mutationFn: () => api.generateProject(projectId),
    onMutate: () => {
      setProgress({
        fraction: 0.08,
        message: "Starting pipeline generate…",
        stages: { Domain: 0.2 },
        currentStage: "Domain",
        etaSeconds: 180,
        gpuUsage: 0.2,
        costUsd: 0.12,
      });
    },
    onSuccess: () => {
      setProgress({
        fraction: api.usingMocks() ? 0.85 : 0.35,
        message: api.usingMocks()
          ? "Mock generate accepted."
          : "Generation accepted. Watching websocket…",
        stages: api.usingMocks()
          ? {
              Domain: 1,
              Research: 1,
              Director: 0.9,
              Review: 0.6,
            }
          : { Research: 0.4, Director: 0.1 },
        currentStage: api.usingMocks() ? "Review" : "Research",
        etaSeconds: api.usingMocks() ? 20 : 120,
        gpuUsage: 0.45,
      });
    },
  });

  const project = projectQuery.data;
  const board = storyboardQuery.data;

  if (projectQuery.isLoading) {
    return <p className="text-muted-foreground">Loading project…</p>;
  }

  if (!project) {
    return <p className="text-danger">Project not found.</p>;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="space-y-4">
        <p className="text-sm uppercase tracking-[0.2em] text-accent">Project</p>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="font-display text-4xl md:text-5xl">{project.topic}</h1>
            <p className="mt-2 text-sm text-muted-foreground">{project.id}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
            >
              <Play className="h-4 w-4" />
              Generate
            </Button>
            <Button asChild variant="secondary">
              <Link href={`/projects/${project.id}/storyboard`}>
                <Clapperboard className="h-4 w-4" />
                Open storyboard
              </Link>
            </Button>
            <Button asChild variant="secondary">
              <Link href={`/projects/${project.id}/timeline`}>
                <ListVideo className="h-4 w-4" />
                Timeline
              </Link>
            </Button>
            <Button asChild variant="secondary">
              <Link href={`/projects/${project.id}/audio`}>
                <Mic2 className="h-4 w-4" />
                Audio
              </Link>
            </Button>
            <Button asChild variant="secondary">
              <Link href={`/projects/${project.id}/export`}>
                <Upload className="h-4 w-4" />
                Export
              </Link>
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>{titleCase(project.status)}</Badge>
          <Badge>{project.scene_count} scenes</Badge>
          {project.has_memory ? <Badge>Memory</Badge> : null}
          {project.has_storyboard ? <Badge>Storyboard</Badge> : null}
          <ReviewBadge
            score={board?.review?.overall_score}
            approved={board?.review?.approved}
          />
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-display text-2xl">Pipeline</h2>
          <ol className="mt-4 space-y-3 text-sm text-muted-foreground">
            <li>1. Research + World Builder</li>
            <li>2. Story Planner / Director</li>
            <li>3. Storyboard Studio review</li>
            <li>4. Approve scenes → images → videos</li>
          </ol>
          <p className="mt-4 flex items-center gap-2 text-sm text-accent">
            <Sparkles className="h-4 w-4" />
            Uses FastAPI <code className="text-xs">POST /projects/{"{id}"}/generate</code>
          </p>
        </section>

        <div className="space-y-4">
          <CostEstimatePanel estimate={mockCostEstimate} />
          <ProgressPanel />
        </div>
      </div>

      {board?.scenes?.length ? (
        <section>
          <h2 className="mb-3 font-display text-2xl">Scene overview</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {board.scenes.map((scene) => (
              <div
                key={scene.id}
                className="rounded-xl border border-border bg-card p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-display text-xl">
                    {scene.id}. {scene.title}
                  </h3>
                  <Badge>{titleCase(scene.status)}</Badge>
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
                  {scene.description}
                </p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
