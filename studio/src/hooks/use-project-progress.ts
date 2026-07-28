"use client";

import { useEffect, useRef } from "react";

import { api } from "@/lib/api/client";
import type { ProgressEvent } from "@/lib/api/types";
import { useUiStore } from "@/stores/ui-store";

function activeStage(stages?: Record<string, number>): string {
  if (!stages) return "";
  const entries = Object.entries(stages);
  if (!entries.length) return "";
  const incomplete = entries.find(([, value]) => value < 0.999);
  return (incomplete ?? entries[entries.length - 1])[0];
}

function estimateEta(
  fraction: number | null | undefined,
  gpuSecondsHint = 420,
): number | null {
  if (fraction == null || fraction <= 0 || fraction >= 1) return null;
  return Math.max(5, Math.round((1 - fraction) * gpuSecondsHint));
}

/**
 * Subscribe to FastAPI `/ws/projects/{id}` progress events.
 * In mock mode, no socket is opened (generate can still push fake progress).
 */
export function useProjectProgress(projectId: string | undefined) {
  const setProgress = useUiStore((state) => state.setProgress);
  const resetProgress = useUiStore((state) => state.resetProgress);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!projectId) return;

    const url = api.websocketUrl(projectId);
    if (!url) return;

    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(String(event.data)) as ProgressEvent;
        const stages = data.stages ?? {};
        const fraction =
          data.fraction ??
          (Object.keys(stages).length
            ? Object.values(stages).reduce((a, b) => a + b, 0) /
              Object.keys(stages).length
            : undefined);
        const stage = activeStage(stages) || data.type;
        const payloadCost =
          typeof data.payload?.estimated_cost_usd === "number"
            ? data.payload.estimated_cost_usd
            : typeof data.payload?.cost_usd === "number"
              ? data.payload.cost_usd
              : undefined;
        const gpu =
          typeof data.payload?.gpu_usage === "number"
            ? data.payload.gpu_usage
            : typeof data.payload?.estimated_gpu_seconds === "number"
              ? Math.min(
                  1,
                  Number(data.payload.estimated_gpu_seconds) / 600,
                )
              : fraction ?? undefined;

        if (data.type === "complete") {
          setProgress({
            fraction: 1,
            message: data.message || "Pipeline complete",
            stages,
            currentStage: "Complete",
            etaSeconds: 0,
            costUsd: payloadCost,
            gpuUsage: gpu ?? 0,
          });
          return;
        }

        if (data.type === "error") {
          setProgress({
            fraction: fraction ?? 0,
            message: data.message || "Pipeline error",
            stages,
            currentStage: "Error",
            etaSeconds: null,
          });
          return;
        }

        setProgress({
          fraction: fraction ?? undefined,
          message: data.message || `${data.type}`,
          stages: Object.keys(stages).length ? stages : undefined,
          currentStage: stage,
          etaSeconds: estimateEta(fraction),
          costUsd: payloadCost,
          gpuUsage: gpu ?? null,
        });
      } catch {
        // ignore malformed frames
      }
    };

    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [projectId, setProgress]);

  return { resetProgress };
}
