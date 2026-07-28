"use client";

import { create } from "zustand";

interface UiState {
  sidebarOpen: boolean;
  activeProjectId: string | null;
  selectedSceneId: number | null;
  compareVersion: number | null;
  progressOpen: boolean;
  progressFraction: number;
  progressMessage: string;
  progressStages: Record<string, number>;
  currentStage: string;
  etaSeconds: number | null;
  costUsd: number | null;
  gpuUsage: number | null;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  setActiveProjectId: (id: string | null) => void;
  selectScene: (id: number | null) => void;
  setCompareVersion: (version: number | null) => void;
  setProgressOpen: (open: boolean) => void;
  setProgress: (payload: {
    fraction?: number;
    message?: string;
    stages?: Record<string, number>;
    currentStage?: string;
    etaSeconds?: number | null;
    costUsd?: number | null;
    gpuUsage?: number | null;
  }) => void;
  resetProgress: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  activeProjectId: null,
  selectedSceneId: null,
  compareVersion: null,
  progressOpen: false,
  progressFraction: 0,
  progressMessage: "",
  progressStages: {},
  currentStage: "",
  etaSeconds: null,
  costUsd: null,
  gpuUsage: null,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setActiveProjectId: (id) => set({ activeProjectId: id }),
  selectScene: (id) => set({ selectedSceneId: id, compareVersion: null }),
  setCompareVersion: (version) => set({ compareVersion: version }),
  setProgressOpen: (open) => set({ progressOpen: open }),
  setProgress: (payload) =>
    set((state) => ({
      progressOpen: true,
      progressFraction:
        payload.fraction !== undefined
          ? payload.fraction
          : state.progressFraction,
      progressMessage: payload.message ?? state.progressMessage,
      progressStages: payload.stages ?? state.progressStages,
      currentStage:
        payload.currentStage !== undefined
          ? payload.currentStage
          : state.currentStage,
      etaSeconds:
        payload.etaSeconds !== undefined
          ? payload.etaSeconds
          : state.etaSeconds,
      costUsd:
        payload.costUsd !== undefined ? payload.costUsd : state.costUsd,
      gpuUsage:
        payload.gpuUsage !== undefined ? payload.gpuUsage : state.gpuUsage,
    })),
  resetProgress: () =>
    set({
      progressFraction: 0,
      progressMessage: "",
      progressStages: {},
      currentStage: "",
      etaSeconds: null,
      costUsd: null,
      gpuUsage: null,
      progressOpen: false,
    }),
}));
