"use client";

import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { SceneCard, SortableSceneCard } from "@/components/storyboard/SceneCard";
import { api } from "@/lib/api/client";
import type { SceneCard as SceneCardModel } from "@/lib/api/types";
import { useUiStore } from "@/stores/ui-store";

export function StoryboardCanvas({
  projectId,
  scenes,
}: {
  projectId: string;
  scenes: SceneCardModel[];
}) {
  const selectedSceneId = useUiStore((state) => state.selectedSceneId);
  const selectScene = useUiStore((state) => state.selectScene);
  const queryClient = useQueryClient();
  const [items, setItems] = useState(scenes);

  useEffect(() => {
    setItems(scenes);
  }, [scenes]);

  useEffect(() => {
    if (!selectedSceneId && items[0]) selectScene(items[0].id);
  }, [items, selectedSceneId, selectScene]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const reorderMutation = useMutation({
    mutationFn: (sceneIds: number[]) => api.reorderScenes(projectId, sceneIds),
    onSuccess: (board) => {
      queryClient.setQueryData(["storyboard", projectId], board);
    },
    onError: () => {
      setItems(scenes);
    },
  });

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = items.findIndex((scene) => scene.id === active.id);
    const newIndex = items.findIndex((scene) => scene.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(items, oldIndex, newIndex);
    setItems(next);
    reorderMutation.mutate(next.map((scene) => scene.id));
  }

  if (!items.length) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/60 p-10 text-center text-muted-foreground">
        No scenes yet. Run generate on the project to build a storyboard.
      </div>
    );
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl">Storyboard canvas</h2>
          <p className="text-sm text-muted-foreground">
            Drag the grip to reorder. Click a card to inspect.
          </p>
        </div>
        {reorderMutation.isPending ? (
          <p className="text-xs text-accent">Saving order…</p>
        ) : null}
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
      >
        <SortableContext
          items={items.map((scene) => scene.id)}
          strategy={rectSortingStrategy}
        >
          <div className="grid gap-4 md:grid-cols-2">
            {items.map((scene) => (
              <SortableSceneCard
                key={scene.id}
                scene={scene}
                selected={selectedSceneId === scene.id}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </section>
  );
}

/** @deprecated Prefer StoryboardCanvas — kept for compatibility. */
export function StoryboardGrid({ scenes }: { scenes: SceneCardModel[] }) {
  const selectedSceneId = useUiStore((state) => state.selectedSceneId);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {scenes.map((scene) => (
        <SceneCard
          key={scene.id}
          scene={scene}
          selected={selectedSceneId === scene.id}
        />
      ))}
    </div>
  );
}
