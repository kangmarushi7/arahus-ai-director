"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { ArrowLeft } from "lucide-react";

import { TimelineEditor } from "@/components/timeline/TimelineEditor";
import { Button } from "@/components/ui/button";
import { useUiStore } from "@/stores/ui-store";

export default function TimelinePage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const setActiveProjectId = useUiStore((state) => state.setActiveProjectId);

  useEffect(() => {
    setActiveProjectId(projectId);
  }, [projectId, setActiveProjectId]);

  return (
    <div className="mx-auto max-w-[1400px] space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="mb-2 px-0">
          <Link href={`/projects/${projectId}/storyboard`}>
            <ArrowLeft className="h-4 w-4" />
            Back to storyboard
          </Link>
        </Button>
        <p className="text-sm uppercase tracking-[0.2em] text-accent">
          Timeline editor
        </p>
        <h1 className="font-display text-4xl md:text-5xl">Edit sequence</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Non-destructive multi-track editing. Clips reference existing
          storyboard assets — media is never regenerated here.
        </p>
      </div>
      <TimelineEditor projectId={projectId} />
    </div>
  );
}
