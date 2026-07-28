"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { SceneCard } from "@/lib/api/types";

function Field({
  label,
  value,
  onChange,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
}) {
  const className =
    "mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring";
  return (
    <label className="block text-sm">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {multiline ? (
        <textarea
          className={`${className} min-h-[88px] resize-y`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          className={className}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  );
}

export function SceneInspector({
  projectId,
  scene,
}: {
  projectId: string;
  scene: SceneCard | null;
}) {
  const queryClient = useQueryClient();
  const exportQuery = useQuery({
    queryKey: ["export", projectId],
    queryFn: () => api.getExport(projectId),
    enabled: Boolean(projectId),
  });

  const [draft, setDraft] = useState({
    camera: "",
    lighting: "",
    emotion: "",
    image_prompt: "",
    characters: "",
    location: "",
    continuity: "",
  });

  useEffect(() => {
    if (!scene) return;
    setDraft({
      camera: scene.camera ?? "",
      lighting: scene.lighting ?? "",
      emotion: scene.emotion ?? "",
      image_prompt: scene.image_prompt ?? "",
      characters: (scene.characters ?? []).join(", "),
      location: scene.location ?? "",
      continuity: scene.scene_plan?.continuity ?? "",
    });
  }, [scene]);

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!scene) throw new Error("No scene");
      return api.patchScene(projectId, scene.id, {
        camera: draft.camera,
        lighting: draft.lighting,
        emotion: draft.emotion,
        image_prompt: draft.image_prompt,
        characters: draft.characters
          .split(",")
          .map((part) => part.trim())
          .filter(Boolean),
        location: draft.location,
        continuity: draft.continuity,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storyboard", projectId] });
    },
  });

  if (!scene) {
    return (
      <section className="rounded-xl border border-border bg-card p-4">
        <h3 className="font-display text-xl">Scene inspector</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Select a scene on the canvas to edit camera, lighting, and continuity.
        </p>
      </section>
    );
  }

  const memory = exportQuery.data?.memory;
  const continuityMeta = scene.scene_plan?.continuity_meta;
  const worldHint =
    memory?.world?.locations?.find(
      (location) => location.name === draft.location,
    )?.description ??
    memory?.world?.era ??
    "";

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-xl">Scene inspector</h3>
          <p className="text-sm text-muted-foreground">
            Scene {scene.id} · {scene.title}
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
        >
          {saveMutation.isPending ? "Saving…" : "Save"}
        </Button>
      </div>

      <div className="mt-4 space-y-3">
        <Field
          label="Camera"
          value={draft.camera}
          onChange={(value) => setDraft((prev) => ({ ...prev, camera: value }))}
        />
        <Field
          label="Lighting"
          value={draft.lighting}
          onChange={(value) =>
            setDraft((prev) => ({ ...prev, lighting: value }))
          }
        />
        <Field
          label="Emotion"
          value={draft.emotion}
          onChange={(value) =>
            setDraft((prev) => ({ ...prev, emotion: value }))
          }
        />
        <Field
          label="Prompt"
          value={draft.image_prompt}
          multiline
          onChange={(value) =>
            setDraft((prev) => ({ ...prev, image_prompt: value }))
          }
        />
        <Field
          label="Character"
          value={draft.characters}
          onChange={(value) =>
            setDraft((prev) => ({ ...prev, characters: value }))
          }
        />
        <Field
          label="World / location"
          value={draft.location}
          onChange={(value) =>
            setDraft((prev) => ({ ...prev, location: value }))
          }
        />
        <Field
          label="Continuity"
          value={draft.continuity}
          multiline
          onChange={(value) =>
            setDraft((prev) => ({ ...prev, continuity: value }))
          }
        />
      </div>

      {(continuityMeta || worldHint || memory?.characters?.length) && (
        <div className="mt-4 space-y-2 rounded-lg bg-muted/40 p-3 text-xs text-muted-foreground">
          {memory?.characters?.[0] ? (
            <p>
              <span className="font-medium text-foreground">Bible · </span>
              {memory.characters[0].name}: {memory.characters[0].appearance}
            </p>
          ) : null}
          {worldHint ? (
            <p>
              <span className="font-medium text-foreground">World · </span>
              {worldHint}
            </p>
          ) : null}
          {continuityMeta ? (
            <p>
              <span className="font-medium text-foreground">Keep · </span>
              {(continuityMeta.keep ?? []).join(", ") || "—"}
              {" · "}
              <span className="font-medium text-foreground">Change · </span>
              {(continuityMeta.change ?? []).join(", ") || "—"}
            </p>
          ) : null}
        </div>
      )}

      {saveMutation.isError ? (
        <p className="mt-2 text-xs text-danger">Could not save scene.</p>
      ) : null}
      {saveMutation.isSuccess ? (
        <p className="mt-2 text-xs text-success">Scene saved.</p>
      ) : null}
    </section>
  );
}
