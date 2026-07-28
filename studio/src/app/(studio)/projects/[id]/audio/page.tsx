"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { ArrowLeft } from "lucide-react";

import { AudioStudio } from "@/components/audio/AudioStudio";
import { Button } from "@/components/ui/button";
import { useUiStore } from "@/stores/ui-store";

export default function AudioPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const setActiveProjectId = useUiStore((state) => state.setActiveProjectId);

  useEffect(() => {
    setActiveProjectId(projectId);
  }, [projectId, setActiveProjectId]);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="mb-2 px-0">
          <Link href={`/projects/${projectId}/timeline`}>
            <ArrowLeft className="h-4 w-4" />
            Back to timeline
          </Link>
        </Button>
        <p className="text-sm uppercase tracking-[0.2em] text-accent">
          Voice & audio
        </p>
        <h1 className="font-display text-4xl md:text-5xl">Audio Studio</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Provider-agnostic voice, music, SFX, subtitles, and dubbing. No vendor
          SDKs in the UI — synthesis goes through the audio router stub until a
          worker is attached.
        </p>
      </div>
      <AudioStudio projectId={projectId} />
    </div>
  );
}
