import {
  mockApiStatus,
  mockAssets,
  mockChatExecute,
  mockChatHistory,
  mockChatPropose,
  mockChatRedo,
  mockChatUndo,
  mockCostEstimate,
  mockDeleteClip,
  mockDuplicateClip,
  mockEnqueueExport,
  mockExport,
  mockGetAudio,
  mockGetTimeline,
  mockGenerateNarration,
  mockMoveClip,
  mockProjects,
  mockReorderTimeline,
  mockResizeClip,
  mockSeekTimeline,
  mockSetMixer,
  mockSetTransition,
  mockSplitClip,
  mockStoryboards,
  mockSyncTimeline,
  mockAudioMusic,
  mockAudioSfx,
  mockAutoSubtitles,
  mockExportAudioTimeline,
  mockListExportPresets,
  mockListPublishProviders,
  mockGetExportStudio,
  mockEnqueueRender,
  mockExportJobAction,
  mockPublish,
} from "@/lib/mocks/data";
import type {
  ApiStatus,
  AssetItem,
  AudioProject,
  ChatHistory,
  ChatResponse,
  CostEstimate,
  ExportAspect,
  ExportFormat,
  ExportPreset,
  ExportPresetId,
  ExportStudioState,
  MixerState,
  Project,
  ProjectExport,
  PublishPlatform,
  PublishProviderHealth,
  SceneCard,
  ScenePatch,
  Storyboard,
  Timeline,
  TransitionType,
} from "@/lib/api/types";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ??
  // Same-origin Railway / production default (Caddy strips /backend → API).
  (process.env.NODE_ENV === "production" ? "/backend" : "")
);
const FORCE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";
const API_KEY =
  process.env.NEXT_PUBLIC_ARAHUS_API_KEY?.trim() ||
  process.env.NEXT_PUBLIC_API_KEY?.trim() ||
  "";

function inMockMode(): boolean {
  return FORCE_MOCKS || !API_URL;
}
function normalizeScene(raw: SceneCard): SceneCard {
  const reviewScore =
    raw.review_score ?? raw.review?.overall_score ?? null;
  return {
    ...raw,
    characters: raw.characters ?? [],
    versions: raw.versions ?? [],
    review_score: reviewScore,
  };
}

function normalizeStoryboard(board: Storyboard): Storyboard {
  return {
    ...board,
    scenes: (board.scenes ?? []).map(normalizeScene),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (inMockMode()) {
    throw new Error("MOCK_MODE");
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(API_KEY
        ? { Authorization: `Bearer ${API_KEY}`, "X-API-Key": API_KEY }
        : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

async function withMockFallback<T>(
  live: () => Promise<T>,
  mock: () => T | Promise<T>,
): Promise<T> {
  try {
    return await live();
  } catch {
    return mock();
  }
}

export const api = {
  async listProjects(): Promise<Project[]> {
    return withMockFallback(
      async () => {
        const data = await request<{ projects: Project[] }>("/projects");
        return data.projects;
      },
      () => mockProjects,
    );
  },

  async getProject(id: string): Promise<Project> {
    return withMockFallback(
      () => request<Project>(`/projects/${id}`),
      () => {
        const found = mockProjects.find((project) => project.id === id);
        if (!found) throw new Error(`Project ${id} not found`);
        return found;
      },
    );
  },

  async createProject(topic: string): Promise<Project> {
    return withMockFallback(
      () =>
        request<Project>("/projects", {
          method: "POST",
          body: JSON.stringify({ topic }),
        }),
      () => {
        const created: Project = {
          id: `mock_${Date.now()}`,
          topic,
          status: "created",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          scene_count: 0,
          has_memory: false,
          has_storyboard: false,
        };
        mockProjects.unshift(created);
        return created;
      },
    );
  },

  async getStoryboard(projectId: string): Promise<Storyboard> {
    return withMockFallback(
      async () =>
        normalizeStoryboard(
          await request<Storyboard>(`/projects/${projectId}/storyboard`),
        ),
      () => {
        const board = mockStoryboards[projectId];
        if (!board) {
          return normalizeStoryboard({
            project_id: projectId,
            topic: "Untitled",
            scenes: [],
            status: "draft",
            version: 1,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            review: null,
          });
        }
        return normalizeStoryboard(structuredClone(board));
      },
    );
  },

  async reorderScenes(
    projectId: string,
    sceneIds: number[],
  ): Promise<Storyboard> {
    return withMockFallback(
      async () =>
        normalizeStoryboard(
          await request<Storyboard>(
            `/projects/${projectId}/storyboard/order`,
            {
              method: "PUT",
              body: JSON.stringify({ scene_ids: sceneIds }),
            },
          ),
        ),
      () => {
        const board = mockStoryboards[projectId];
        if (!board) throw new Error("Storyboard not found");
        const byId = new Map(board.scenes.map((scene) => [scene.id, scene]));
        board.scenes = sceneIds.map((id) => {
          const scene = byId.get(id);
          if (!scene) throw new Error(`Unknown scene ${id}`);
          return scene;
        });
        board.version += 1;
        board.updated_at = new Date().toISOString();
        return normalizeStoryboard(structuredClone(board));
      },
    );
  },

  async patchScene(
    projectId: string,
    sceneId: number,
    patch: ScenePatch,
  ): Promise<SceneCard> {
    return withMockFallback(
      async () =>
        normalizeScene(
          await request<SceneCard>(
            `/storyboard/${sceneId}?project_id=${encodeURIComponent(projectId)}`,
            {
              method: "PATCH",
              body: JSON.stringify(patch),
            },
          ),
        ),
      () => {
        const board = mockStoryboards[projectId];
        if (!board) throw new Error("Storyboard not found");
        const index = board.scenes.findIndex((scene) => scene.id === sceneId);
        if (index < 0) throw new Error(`Scene ${sceneId} not found`);
        const current = board.scenes[index];
        const next: SceneCard = {
          ...current,
          ...patch,
          status: (patch.status as SceneCard["status"]) ?? current.status,
          characters: patch.characters ?? current.characters,
          version: current.version + 1,
          versions: [
            ...(current.versions ?? []),
            {
              version: current.version,
              created_at: new Date().toISOString(),
              status: current.status,
              title: current.title,
              description: current.description,
              goal: current.goal,
              image_prompt: current.image_prompt,
              camera: current.camera,
              emotion: current.emotion,
              lighting: current.lighting,
              change_summary: "mock patch",
              review_score: current.review_score ?? null,
            },
          ],
          scene_plan: current.scene_plan
            ? {
                ...current.scene_plan,
                continuity:
                  patch.continuity ?? current.scene_plan.continuity,
              }
            : current.scene_plan,
        };
        board.scenes[index] = next;
        board.updated_at = new Date().toISOString();
        return normalizeScene(structuredClone(next));
      },
    );
  },

  async generateSceneImage(
    projectId: string,
    sceneId: number,
    opts?: { dryRun?: boolean; profile?: string | null },
  ): Promise<{
    status: string;
    url?: string | null;
    estimate?: CostEstimate | null;
    storyboard_scene?: SceneCard | null;
  }> {
    return withMockFallback(
      () =>
        request(`/scene/${sceneId}/image`, {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            dry_run: opts?.dryRun ?? false,
            profile: opts?.profile ?? null,
          }),
        }),
      () => {
        const board = mockStoryboards[projectId];
        const scene = board?.scenes.find((item) => item.id === sceneId);
        if (!scene) throw new Error(`Scene ${sceneId} not found`);
        if (opts?.dryRun) {
          return { status: scene.status, estimate: mockCostEstimate };
        }
        const url = `https://picsum.photos/seed/arahus-regen-${sceneId}-${Date.now()}/960/540`;
        scene.image = { url, prompt: scene.image_prompt };
        scene.status = "image_generated";
        scene.version += 1;
        return {
          status: scene.status,
          url,
          storyboard_scene: normalizeScene(structuredClone(scene)),
        };
      },
    );
  },

  async generateSceneVideo(
    projectId: string,
    sceneId: number,
    opts?: { dryRun?: boolean; profile?: string | null },
  ): Promise<{
    status: string;
    url?: string | null;
    estimate?: CostEstimate | null;
    storyboard_scene?: SceneCard | null;
  }> {
    return withMockFallback(
      () =>
        request(`/scene/${sceneId}/video`, {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            dry_run: opts?.dryRun ?? false,
            profile: opts?.profile ?? null,
          }),
        }),
      () => {
        const board = mockStoryboards[projectId];
        const scene = board?.scenes.find((item) => item.id === sceneId);
        if (!scene) throw new Error(`Scene ${sceneId} not found`);
        if (opts?.dryRun) {
          return { status: scene.status, estimate: mockCostEstimate };
        }
        const url =
          "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4";
        scene.video = { url, duration_seconds: scene.duration_seconds };
        scene.status = "video_generated";
        scene.version += 1;
        return {
          status: scene.status,
          url,
          storyboard_scene: normalizeScene(structuredClone(scene)),
        };
      },
    );
  },

  async listAssets(projectId?: string): Promise<AssetItem[]> {
    return withMockFallback(
      async () => {
        const query = projectId
          ? `?project_id=${encodeURIComponent(projectId)}`
          : "";
        const data = await request<{ assets: AssetItem[] }>(`/assets${query}`);
        return data.assets;
      },
      () =>
        projectId
          ? mockAssets.filter(
              (asset) => asset.metadata.project_id === projectId,
            )
          : mockAssets,
    );
  },

  async getExport(projectId: string): Promise<ProjectExport> {
    return withMockFallback(
      () => request<ProjectExport>(`/projects/${projectId}/export`),
      () => mockExport(projectId),
    );
  },

  async getChatHistory(projectId: string): Promise<ChatHistory> {
    return withMockFallback(
      () => request<ChatHistory>(`/projects/${projectId}/chat`),
      () => mockChatHistory(projectId),
    );
  },

  async chat(
    projectId: string,
    message: string,
    selectedSceneId?: number,
  ): Promise<ChatResponse> {
    return withMockFallback(
      () =>
        request<ChatResponse>("/chat", {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            message,
            selected_scene_id: selectedSceneId ?? null,
          }),
        }),
      () => mockChatPropose(projectId, message, selectedSceneId),
    );
  },

  async executeChat(
    projectId: string,
    proposalId?: string,
    runMedia = false,
  ): Promise<{
    reply: string;
    can_undo: boolean;
    can_redo: boolean;
    storyboard?: Storyboard | null;
  }> {
    return withMockFallback(
      () =>
        request("/chat/execute", {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            proposal_id: proposalId ?? null,
            run_media: runMedia,
          }),
        }),
      () => mockChatExecute(projectId, proposalId),
    );
  },

  async undoChat(projectId: string): Promise<{ reply: string; can_undo: boolean; can_redo: boolean }> {
    return withMockFallback(
      () =>
        request("/chat/undo", {
          method: "POST",
          body: JSON.stringify({ project_id: projectId }),
        }),
      () => mockChatUndo(projectId),
    );
  },

  async redoChat(projectId: string): Promise<{ reply: string; can_undo: boolean; can_redo: boolean }> {
    return withMockFallback(
      () =>
        request("/chat/redo", {
          method: "POST",
          body: JSON.stringify({ project_id: projectId }),
        }),
      () => mockChatRedo(projectId),
    );
  },

  async getStatus(): Promise<ApiStatus> {
    return withMockFallback(
      () => request<ApiStatus>("/api/status"),
      () => mockApiStatus,
    );
  },

  async estimateSceneImage(
    projectId: string,
    sceneId: number,
  ): Promise<CostEstimate> {
    const result = await this.generateSceneImage(projectId, sceneId, {
      dryRun: true,
    });
    return result.estimate ?? mockCostEstimate;
  },

  async generateProject(projectId: string): Promise<{ status: string }> {
    return withMockFallback(
      () =>
        request(`/projects/${projectId}/generate`, {
          method: "POST",
          body: JSON.stringify({ sync_studio: true }),
        }),
      async () => ({ status: "generating" }),
    );
  },

  websocketUrl(projectId: string): string | null {
    if (inMockMode()) return null;
    const wsBase = API_URL.replace(/^http/, "ws");
    const base = `${wsBase}/ws/projects/${projectId}`;
    if (!API_KEY) return base;
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}api_key=${encodeURIComponent(API_KEY)}`;
  },

  usingMocks(): boolean {
    return inMockMode();
  },

  async getTimeline(projectId: string): Promise<Timeline> {
    return withMockFallback(
      () => request<Timeline>(`/projects/${projectId}/timeline`),
      () => mockGetTimeline(projectId),
    );
  },

  async syncTimeline(projectId: string): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(`/projects/${projectId}/timeline/sync`, {
          method: "POST",
          body: JSON.stringify({ preserve_non_video: true }),
        }),
      () => mockSyncTimeline(projectId),
    );
  },

  async reorderTimeline(
    projectId: string,
    trackId: string,
    clipIds: string[],
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(`/projects/${projectId}/timeline/order`, {
          method: "PUT",
          body: JSON.stringify({ track_id: trackId, clip_ids: clipIds }),
        }),
      () => mockReorderTimeline(projectId, trackId, clipIds),
    );
  },

  async resizeTimelineClip(
    projectId: string,
    clipId: string,
    durationSeconds: number,
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(
          `/projects/${projectId}/timeline/clips/${clipId}/resize`,
          {
            method: "POST",
            body: JSON.stringify({ duration_seconds: durationSeconds }),
          },
        ),
      () => mockResizeClip(projectId, clipId, durationSeconds),
    );
  },

  async moveTimelineClip(
    projectId: string,
    clipId: string,
    startSeconds: number,
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(
          `/projects/${projectId}/timeline/clips/${clipId}/move`,
          {
            method: "POST",
            body: JSON.stringify({ start_seconds: startSeconds }),
          },
        ),
      () => mockMoveClip(projectId, clipId, startSeconds),
    );
  },

  async splitTimelineClip(
    projectId: string,
    clipId: string,
    atSeconds: number,
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(
          `/projects/${projectId}/timeline/clips/${clipId}/split`,
          {
            method: "POST",
            body: JSON.stringify({ at_seconds: atSeconds }),
          },
        ),
      () => mockSplitClip(projectId, clipId, atSeconds),
    );
  },

  async deleteTimelineClip(
    projectId: string,
    clipId: string,
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(
          `/projects/${projectId}/timeline/clips/${clipId}?close_gaps=true`,
          { method: "DELETE" },
        ),
      () => mockDeleteClip(projectId, clipId),
    );
  },

  async duplicateTimelineClip(
    projectId: string,
    clipId: string,
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(
          `/projects/${projectId}/timeline/clips/${clipId}/duplicate`,
          { method: "POST", body: "{}" },
        ),
      () => mockDuplicateClip(projectId, clipId),
    );
  },

  async setTimelineTransition(
    projectId: string,
    clipId: string,
    transition: TransitionType,
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(
          `/projects/${projectId}/timeline/clips/${clipId}/transition`,
          {
            method: "POST",
            body: JSON.stringify({
              transition_out: transition,
              transition_duration: transition === "cut" ? 0 : 0.5,
            }),
          },
        ),
      () => mockSetTransition(projectId, clipId, transition),
    );
  },

  async seekTimeline(projectId: string, seconds: number): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(`/projects/${projectId}/timeline/seek`, {
          method: "POST",
          body: JSON.stringify({ seconds }),
        }),
      () => mockSeekTimeline(projectId, seconds),
    );
  },

  async enqueueTimelineExport(
    projectId: string,
    aspect: ExportAspect,
  ): Promise<Timeline> {
    return withMockFallback(
      () =>
        request<Timeline>(`/projects/${projectId}/timeline/export`, {
          method: "POST",
          body: JSON.stringify({ format: "mp4", aspect }),
        }),
      () => mockEnqueueExport(projectId, aspect),
    );
  },

  async getAudio(projectId: string): Promise<AudioProject> {
    return withMockFallback(
      () => request<AudioProject>(`/projects/${projectId}/audio`),
      () => mockGetAudio(projectId),
    );
  },

  async generateNarration(projectId: string): Promise<AudioProject> {
    return withMockFallback(
      () =>
        request<AudioProject>(
          `/projects/${projectId}/audio/narration/generate`,
          { method: "POST", body: "{}" },
        ),
      () => mockGenerateNarration(projectId),
    );
  },

  async addMusic(
    projectId: string,
    mood: string,
  ): Promise<AudioProject> {
    return withMockFallback(
      () =>
        request<AudioProject>(`/projects/${projectId}/audio/music`, {
          method: "POST",
          body: JSON.stringify({ mood, duration: 30, generate: true }),
        }),
      () => mockAudioMusic(projectId, mood),
    );
  },

  async addSfx(projectId: string, description: string): Promise<AudioProject> {
    return withMockFallback(
      () =>
        request<AudioProject>(`/projects/${projectId}/audio/sfx`, {
          method: "POST",
          body: JSON.stringify({
            description,
            kind: "scene",
            generate: true,
          }),
        }),
      () => mockAudioSfx(projectId, description),
    );
  },

  async autoSubtitles(projectId: string): Promise<AudioProject> {
    return withMockFallback(
      () =>
        request<AudioProject>(`/projects/${projectId}/audio/subtitles/auto`, {
          method: "POST",
          body: "{}",
        }),
      () => mockAutoSubtitles(projectId),
    );
  },

  async setMixer(
    projectId: string,
    mixer: MixerState,
  ): Promise<AudioProject> {
    return withMockFallback(
      () =>
        request<AudioProject>(`/projects/${projectId}/audio/mixer`, {
          method: "PUT",
          body: JSON.stringify(mixer),
        }),
      () => mockSetMixer(projectId, mixer),
    );
  },

  async exportAudioTimeline(projectId: string): Promise<{
    audio: AudioProject;
    timeline: Timeline;
  }> {
    return withMockFallback(
      () =>
        request(`/projects/${projectId}/audio/export-timeline`, {
          method: "POST",
          body: "{}",
        }),
      () => mockExportAudioTimeline(projectId),
    );
  },

  async listExportPresets(): Promise<ExportPreset[]> {
    return withMockFallback(
      async () => {
        const data = await request<{ presets: ExportPreset[] }>("/export/presets");
        return data.presets;
      },
      () => mockListExportPresets(),
    );
  },

  async listPublishProviders(): Promise<PublishProviderHealth[]> {
    return withMockFallback(
      async () => {
        const data = await request<{ providers: PublishProviderHealth[] }>(
          "/export/providers",
        );
        return data.providers;
      },
      () => mockListPublishProviders(),
    );
  },

  async getExportStudio(projectId: string): Promise<ExportStudioState> {
    return withMockFallback(
      () => request<ExportStudioState>(`/projects/${projectId}/exports`),
      () => mockGetExportStudio(projectId),
    );
  },

  async enqueueExport(
    projectId: string,
    body: {
      preset?: ExportPresetId;
      format?: ExportFormat;
      width?: number;
      height?: number;
      fps?: number;
      aspect?: string;
      process?: boolean;
    },
  ): Promise<ExportStudioState> {
    return withMockFallback(
      () =>
        request<ExportStudioState>(`/projects/${projectId}/exports`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      () =>
        mockEnqueueRender(projectId, {
          preset: body.preset,
          format: body.format,
          process: body.process,
        }),
    );
  },

  async exportJobAction(
    projectId: string,
    jobId: string,
    action: "cancel" | "pause" | "resume" | "retry",
  ): Promise<ExportStudioState> {
    return withMockFallback(
      () =>
        request<ExportStudioState>(
          `/projects/${projectId}/exports/${jobId}/${action}`,
          { method: "POST", body: "{}" },
        ),
      () => mockExportJobAction(projectId, jobId, action),
    );
  },

  async publishExport(
    projectId: string,
    body: {
      render_job_id: string;
      platform: PublishPlatform;
      title?: string;
      description?: string;
      tags?: string[];
      schedule_at?: string | null;
      run?: boolean;
    },
  ): Promise<ExportStudioState> {
    return withMockFallback(
      () =>
        request<ExportStudioState>(`/projects/${projectId}/publish`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      () => mockPublish(projectId, body),
    );
  },
};
