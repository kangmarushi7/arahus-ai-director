import type {
  ApiStatus,
  AssetItem,
  AudioProject,
  ChatHistory,
  ChatMessage,
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
  PublishJob,
  PublishPlatform,
  PublishProviderHealth,
  RenderJob,
  SceneCard,
  Storyboard,
  Timeline,
  TimelineClip,
  TimelinePreview,
  TimelineTrack,
  TransitionType,
} from "@/lib/api/types";

const now = new Date().toISOString();

export const mockProjects: Project[] = [
  {
    id: "napoleon_alps_a1b2c3d4e5",
    topic: "Napoleon crossing the Alps",
    status: "ready",
    created_at: now,
    updated_at: now,
    last_run_id: "run-001",
    scene_count: 4,
    has_memory: true,
    has_storyboard: true,
  },
  {
    id: "constantinople_f6e5d4c3b2",
    topic: "The Fall of Constantinople",
    status: "generating",
    created_at: now,
    updated_at: now,
    last_run_id: "run-002",
    scene_count: 4,
    has_memory: true,
    has_storyboard: true,
  },
  {
    id: "mars_colony_9988776655",
    topic: "Life on Mars in 2150",
    status: "created",
    created_at: now,
    updated_at: now,
    scene_count: 0,
    has_memory: false,
    has_storyboard: false,
  },
];

const scene = (
  id: number,
  title: string,
  partial: Partial<SceneCard> = {},
): SceneCard => ({
  id,
  title,
  description: `${title} — cinematic beat with period-accurate detail and motivated light.`,
  goal: title,
  duration_seconds: id === 3 ? 8 : 5,
  characters: ["Napoleon Bonaparte"],
  location: "Great St Bernard Pass",
  camera: id === 3 ? "Close Up, Slow Dolly In" : "Wide establishing, static",
  emotion: id === 3 ? "Tension" : "Resolve",
  lighting: "Golden Hour",
  image_prompt: `cinematic still of ${title.toLowerCase()}, bicorne silhouette, alpine ridge`,
  negative_prompt: "modern clothing, anachronism, text, watermark",
  status: partial.status ?? "image_approved",
  version: 2,
  versions: [
    {
      version: 1,
      created_at: now,
      status: "draft",
      title,
      image_prompt: `draft prompt for ${title}`,
      camera: "Wide",
      emotion: "Neutral",
      lighting: "Overcast",
      change_summary: "initial draft",
      review_score: 72,
    },
  ],
  scene_plan: {
    id,
    title,
    environment: "Great St Bernard Pass",
    camera_shot: id === 3 ? "close-up" : "wide",
    camera_angle: "eye-level",
    lens: "35mm",
    camera_movement: id === 3 ? "slow dolly in" : "static",
    lighting: "Golden Hour",
    emotion: id === 3 ? "Tension" : "Resolve",
    continuity: id === 1 ? "Establish column silhouette" : "Match bicorne + coat",
    continuity_meta: {
      previous_scene: id > 1 ? `scene_${id - 1}` : undefined,
      keep: ["character", "costume", "location"],
      change: id === 3 ? ["emotion", "camera"] : ["framing"],
    },
  },
  image: {
    url: `https://picsum.photos/seed/arahus-${id}/960/540`,
    prompt: title,
  },
  video:
    id <= 2
      ? {
          url: "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
          duration_seconds: 5,
        }
      : null,
  review: {
    overall_score: 88 + id,
    approved: true,
  },
  review_score: 88 + id,
  ...partial,
});

export const mockStoryboards: Record<string, Storyboard> = {
  napoleon_alps_a1b2c3d4e5: {
    project_id: "napoleon_alps_a1b2c3d4e5",
    topic: "Napoleon crossing the Alps",
    status: "approved",
    version: 3,
    created_at: now,
    updated_at: now,
    review: {
      overall_score: 91,
      approved: true,
      issues: [],
      recommendations: ["Keep bicorne consistent across scenes"],
    },
    scenes: [
      scene(1, "Dawn Ascent", { status: "video_approved" }),
      scene(2, "The Column", { status: "video_generated" }),
      scene(3, "Reveal Antagonist", {
        status: "image_approved",
        emotion: "Tension",
        camera: "Close Up",
      }),
      scene(4, "Summit", { status: "approved", image: null, video: null }),
    ],
  },
  constantinople_f6e5d4c3b2: {
    project_id: "constantinople_f6e5d4c3b2",
    topic: "The Fall of Constantinople",
    status: "draft",
    version: 1,
    created_at: now,
    updated_at: now,
    review: {
      overall_score: 78,
      approved: false,
      issues: ["Scene 2 lighting drifts from bible"],
      recommendations: ["Lock Character #1 appearance before images"],
    },
    scenes: [
      scene(1, "Theodosian Walls", {
        status: "draft",
        image: null,
        video: null,
        characters: ["Constantine XI"],
        location: "Constantinople",
      }),
      scene(2, "Orban's Cannon", {
        status: "draft",
        image: null,
        video: null,
        characters: ["Mehmed II"],
        location: "Outer ditch",
      }),
      scene(3, "Breach", {
        status: "draft",
        image: null,
        video: null,
        characters: ["Janissaries"],
        location: "Wall breach",
      }),
      scene(4, "Last Stand", {
        status: "draft",
        image: null,
        video: null,
        characters: ["Constantine XI"],
        location: "Gate of St. Romanus",
      }),
    ],
  },
};

export const mockAssets: AssetItem[] = [
  {
    id: 17,
    kind: "character",
    slug: "napoleon",
    label: "Napoleon Bonaparte",
    refs: {},
    metadata: {
      project_id: "napoleon_alps_a1b2c3d4e5",
      appearance: "Bicorne, grey coat, short stature",
    },
  },
  {
    id: 18,
    kind: "location",
    slug: "great_st_bernard_pass",
    label: "Great St Bernard Pass",
    refs: {},
    metadata: {
      project_id: "napoleon_alps_a1b2c3d4e5",
      description: "Snow ridge, mule column, alpine light",
    },
  },
  {
    id: 21,
    kind: "style",
    slug: "napoleonic_cinematic",
    label: "Napoleonic Cinematic",
    refs: {},
    metadata: { project_id: "napoleon_alps_a1b2c3d4e5" },
  },
  {
    id: 19,
    kind: "image",
    slug: "scene_1_image",
    label: "Dawn Ascent",
    refs: { url: "https://picsum.photos/seed/arahus-1/960/540" },
    metadata: { scene_id: 1, project_id: "napoleon_alps_a1b2c3d4e5" },
  },
  {
    id: 20,
    kind: "video",
    slug: "scene_1_video",
    label: "Dawn Ascent Video",
    refs: {
      url: "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
    },
    metadata: { scene_id: 1, project_id: "napoleon_alps_a1b2c3d4e5" },
  },
  {
    id: 22,
    kind: "image",
    slug: "scene_2_image",
    label: "The Column",
    refs: { url: "https://picsum.photos/seed/arahus-2/960/540" },
    metadata: { scene_id: 2, project_id: "napoleon_alps_a1b2c3d4e5" },
  },
];

export function mockExport(projectId: string): ProjectExport {
  return {
    project_id: projectId,
    memory: {
      characters: [
        {
          name: "Napoleon Bonaparte",
          appearance: "Bicorne, grey riding coat, pale complexion",
          role: "protagonist",
        },
      ],
      world: {
        era: "1800",
        locations: [
          {
            name: "Great St Bernard Pass",
            description: "Snowbound alpine ridge with mule paths",
          },
        ],
      },
      style: { look: "painterly cinematic", palette: "cold gold / slate" },
    },
    storyboard: mockStoryboards[projectId] ?? null,
  };
}

export const mockCostEstimate: CostEstimate = {
  image_count: 2,
  video_count: 2,
  scene_ids: [3, 4],
  estimated_gpu_seconds: 420,
  estimated_cost_usd: 0.58,
  estimated_gpu_minutes: 7,
};

export const mockApiStatus: ApiStatus = {
  llm: true,
  runpod: false,
  r2: false,
  database: false,
  allow_stubs: true,
  ready: true,
};

type MockChatState = {
  messages: ChatMessage[];
  pending_proposal_id: string | null;
  undo: Array<{ board: Storyboard }>;
  redo: Array<{ board: Storyboard }>;
  proposals: Record<
    string,
    { lighting?: string; scene_id?: number; order?: number[] }
  >;
};

const mockChat: Record<string, MockChatState> = {};

function chatState(projectId: string): MockChatState {
  if (!mockChat[projectId]) {
    mockChat[projectId] = {
      messages: [],
      pending_proposal_id: null,
      undo: [],
      redo: [],
      proposals: {},
    };
  }
  return mockChat[projectId];
}

export function mockChatHistory(projectId: string): ChatHistory {
  const state = chatState(projectId);
  return {
    project_id: projectId,
    messages: state.messages,
    pending_proposal_id: state.pending_proposal_id,
    can_undo: state.undo.length > 0,
    can_redo: state.redo.length > 0,
  };
}

export function mockChatPropose(
  projectId: string,
  message: string,
  selectedSceneId?: number,
): ChatResponse {
  const state = chatState(projectId);
  const board = mockStoryboards[projectId];
  const sceneMatch = message.match(/scene\s*(\d+)/i);
  const sceneId = sceneMatch
    ? Number(sceneMatch[1])
    : (selectedSceneId ?? 1);
  const proposalId = `mock_${Date.now()}`;
  const lower = message.toLowerCase();

  let commandType = "edit_scene";
  let summary = message;
  const updates: Record<string, unknown> = {};
  const proposal: {
    lighting?: string;
    scene_id?: number;
    order?: number[];
  } = { scene_id: sceneId };

  if (lower.includes("lighting")) {
    commandType = "change_lighting";
    const lighting = lower.includes("moonlight") ? "moonlight" : "soft key";
    updates.lighting = lighting;
    proposal.lighting = lighting;
    summary = `Set scene ${sceneId} lighting to ${lighting}`;
  } else if (lower.includes("reverse")) {
    commandType = "reorder_scenes";
    proposal.order = board
      ? [...board.scenes].reverse().map((scene) => scene.id)
      : [4, 3, 2, 1];
    summary = "Reverse scene order";
  } else if (lower.includes("regenerate image")) {
    commandType = "regenerate_image";
    summary = `Regenerate image for scene ${sceneId}`;
  }

  state.proposals[proposalId] = proposal;
  state.pending_proposal_id = proposalId;
  state.messages.push({
    id: `u_${Date.now()}`,
    role: "user",
    content: message,
    created_at: new Date().toISOString(),
  });
  const preview = {
    summary,
    command_count: 1,
    changes: [
      {
        type: commandType,
        summary,
        scene_id: sceneId,
        updates,
        before_order: board?.scenes.map((scene) => scene.id),
        after_order: proposal.order,
      },
    ],
    requires_confirmation: true,
  };
  const reply = `Proposed 1 change(s). Review the preview, then confirm. ${summary}`;
  state.messages.push({
    id: `a_${Date.now()}`,
    role: "assistant",
    content: reply,
    created_at: new Date().toISOString(),
    proposal_id: proposalId,
    preview,
    commands: [{ type: commandType, scene_id: sceneId, updates, summary }],
  });

  return {
    reply,
    project_id: projectId,
    suggestions: ["Confirm changes"],
    commands: [{ type: commandType, scene_id: sceneId, updates, summary }],
    preview,
    proposal_id: proposalId,
    can_undo: state.undo.length > 0,
    can_redo: state.redo.length > 0,
  };
}

export function mockChatExecute(projectId: string, proposalId?: string) {
  const state = chatState(projectId);
  const id = proposalId ?? state.pending_proposal_id;
  const board = mockStoryboards[projectId];
  if (!id || !board) {
    return { reply: "No pending proposal", can_undo: false, can_redo: false };
  }
  state.undo.push({ board: structuredClone(board) });
  state.redo = [];
  const proposal = state.proposals[id] ?? {};
  if (proposal.lighting && proposal.scene_id) {
    const scene = board.scenes.find((item) => item.id === proposal.scene_id);
    if (scene) scene.lighting = proposal.lighting;
  }
  if (proposal.order) {
    const byId = new Map(board.scenes.map((scene) => [scene.id, scene]));
    board.scenes = proposal.order
      .map((sceneId) => byId.get(sceneId))
      .filter(Boolean) as typeof board.scenes;
  }
  state.pending_proposal_id = null;
  state.messages.push({
    id: `x_${Date.now()}`,
    role: "assistant",
    content: "Executed mock copilot change",
    created_at: new Date().toISOString(),
    executed: true,
    proposal_id: id,
  });
  return {
    reply: "Executed mock copilot change",
    can_undo: true,
    can_redo: false,
    storyboard: structuredClone(board),
  };
}

export function mockChatUndo(projectId: string) {
  const state = chatState(projectId);
  const entry = state.undo.pop();
  const board = mockStoryboards[projectId];
  if (!entry || !board) {
    return { reply: "Nothing to undo", can_undo: false, can_redo: false };
  }
  state.redo.push({ board: structuredClone(board) });
  mockStoryboards[projectId] = entry.board;
  state.messages.push({
    id: `undo_${Date.now()}`,
    role: "system",
    content: "Undid last copilot change",
    created_at: new Date().toISOString(),
  });
  return {
    reply: "Undid last copilot change",
    can_undo: state.undo.length > 0,
    can_redo: true,
  };
}

export function mockChatRedo(projectId: string) {
  const state = chatState(projectId);
  const entry = state.redo.pop();
  const board = mockStoryboards[projectId];
  if (!entry || !board) {
    return { reply: "Nothing to redo", can_undo: false, can_redo: false };
  }
  state.undo.push({ board: structuredClone(board) });
  mockStoryboards[projectId] = entry.board;
  state.messages.push({
    id: `redo_${Date.now()}`,
    role: "system",
    content: "Redid last copilot change",
    created_at: new Date().toISOString(),
  });
  return {
    reply: "Redid last copilot change",
    can_undo: true,
    can_redo: state.redo.length > 0,
  };
}

const mockTimelines: Record<string, Timeline> = {};

function buildMockTimeline(projectId: string): Timeline {
  const board = mockStoryboards[projectId];
  const scenes = board?.scenes ?? [];
  let cursor = 0;
  const clips: TimelineClip[] = scenes.map((scene) => {
    const duration = scene.duration_seconds || 5;
    const clip: TimelineClip = {
      id: `clip_${projectId}_${scene.id}`,
      label: scene.title,
      scene_id: scene.id,
      asset_id: null,
      media_url: scene.video?.url ?? scene.image?.url ?? null,
      poster_url: scene.image?.url ?? null,
      start_seconds: cursor,
      duration_seconds: duration,
      in_point: 0,
      out_point: duration,
      source_duration: duration,
      transition_in: "cut",
      transition_out: "cut",
      transition_duration: 0,
      muted: false,
      text: null,
    };
    cursor += duration;
    return clip;
  });

  const tracks: TimelineTrack[] = [
    {
      id: `track_video_${projectId}`,
      kind: "video",
      name: "Video",
      clips,
      locked: false,
      muted: false,
      height: 72,
    },
    {
      id: `track_voice_${projectId}`,
      kind: "voice",
      name: "Voice",
      clips: [],
      locked: false,
      muted: false,
      height: 48,
    },
    {
      id: `track_music_${projectId}`,
      kind: "music",
      name: "Music",
      clips: [],
      locked: false,
      muted: false,
      height: 48,
    },
    {
      id: `track_sfx_${projectId}`,
      kind: "sfx",
      name: "SFX",
      clips: [],
      locked: false,
      muted: false,
      height: 48,
    },
    {
      id: `track_subs_${projectId}`,
      kind: "subtitles",
      name: "Subtitles",
      clips: scenes.slice(0, 2).map((scene, index) => ({
        id: `sub_${scene.id}`,
        label: `Caption ${scene.id}`,
        scene_id: scene.id,
        start_seconds: index * 5,
        duration_seconds: 4,
        in_point: 0,
        out_point: 4,
        source_duration: 4,
        transition_in: "cut" as TransitionType,
        transition_out: "cut" as TransitionType,
        transition_duration: 0,
        muted: false,
        text: scene.title,
        media_url: null,
        poster_url: null,
        asset_id: null,
      })),
      locked: false,
      muted: false,
      height: 40,
    },
  ];

  return {
    project_id: projectId,
    version: 1,
    tracks,
    export_queue: [],
    playhead_seconds: 0,
    duration_seconds: cursor || 20,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function ensureTimeline(projectId: string): Timeline {
  if (!mockTimelines[projectId]) {
    mockTimelines[projectId] = buildMockTimeline(projectId);
  }
  return mockTimelines[projectId];
}

function withDuration(timeline: Timeline): Timeline {
  const ends = timeline.tracks.flatMap((track) =>
    track.clips.map((clip) => clip.start_seconds + clip.duration_seconds),
  );
  return {
    ...timeline,
    duration_seconds: ends.length ? Math.max(...ends) : 0,
  };
}

export function mockGetTimeline(projectId: string): Timeline {
  return withDuration(structuredClone(ensureTimeline(projectId)));
}

export function mockSyncTimeline(projectId: string): Timeline {
  mockTimelines[projectId] = buildMockTimeline(projectId);
  return mockGetTimeline(projectId);
}

export function mockReorderTimeline(
  projectId: string,
  trackId: string,
  clipIds: string[],
): Timeline {
  const timeline = ensureTimeline(projectId);
  const track = timeline.tracks.find((item) => item.id === trackId);
  if (!track) throw new Error("Track not found");
  const byId = new Map(track.clips.map((clip) => [clip.id, clip]));
  let cursor = 0;
  track.clips = clipIds.map((id) => {
    const clip = byId.get(id)!;
    const next = { ...clip, start_seconds: cursor };
    cursor += clip.duration_seconds;
    return next;
  });
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

export function mockResizeClip(
  projectId: string,
  clipId: string,
  duration: number,
): Timeline {
  const timeline = ensureTimeline(projectId);
  for (const track of timeline.tracks) {
    track.clips = track.clips.map((clip) =>
      clip.id === clipId
        ? {
            ...clip,
            duration_seconds: duration,
            out_point: clip.in_point + duration,
          }
        : clip,
    );
  }
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

export function mockMoveClip(
  projectId: string,
  clipId: string,
  startSeconds: number,
): Timeline {
  const timeline = ensureTimeline(projectId);
  for (const track of timeline.tracks) {
    track.clips = track.clips.map((clip) =>
      clip.id === clipId ? { ...clip, start_seconds: startSeconds } : clip,
    );
  }
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

export function mockSplitClip(
  projectId: string,
  clipId: string,
  atSeconds: number,
): Timeline {
  const timeline = ensureTimeline(projectId);
  for (const track of timeline.tracks) {
    const index = track.clips.findIndex((clip) => clip.id === clipId);
    if (index < 0) continue;
    const clip = track.clips[index];
    const offset = atSeconds - clip.start_seconds;
    const left = {
      ...clip,
      duration_seconds: offset,
      out_point: clip.in_point + offset,
    };
    const right = {
      ...clip,
      id: `${clip.id}_b`,
      start_seconds: atSeconds,
      duration_seconds: clip.duration_seconds - offset,
      in_point: clip.in_point + offset,
      label: `${clip.label} (B)`,
    };
    track.clips.splice(index, 1, left, right);
  }
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

export function mockDeleteClip(projectId: string, clipId: string): Timeline {
  const timeline = ensureTimeline(projectId);
  for (const track of timeline.tracks) {
    track.clips = track.clips.filter((clip) => clip.id !== clipId);
  }
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

export function mockDuplicateClip(projectId: string, clipId: string): Timeline {
  const timeline = ensureTimeline(projectId);
  for (const track of timeline.tracks) {
    const index = track.clips.findIndex((clip) => clip.id === clipId);
    if (index < 0) continue;
    const clip = track.clips[index];
    track.clips.splice(index + 1, 0, {
      ...clip,
      id: `${clip.id}_copy`,
      start_seconds: clip.start_seconds + clip.duration_seconds,
      label: `${clip.label} copy`,
    });
  }
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

export function mockSetTransition(
  projectId: string,
  clipId: string,
  transition: TransitionType,
): Timeline {
  const timeline = ensureTimeline(projectId);
  for (const track of timeline.tracks) {
    track.clips = track.clips.map((clip) =>
      clip.id === clipId
        ? {
            ...clip,
            transition_out: transition,
            transition_duration: transition === "cut" ? 0 : 0.5,
          }
        : clip,
    );
  }
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

export function mockSeekTimeline(
  projectId: string,
  seconds: number,
): Timeline & { preview: TimelinePreview } {
  const timeline = ensureTimeline(projectId);
  timeline.playhead_seconds = seconds;
  const video = timeline.tracks.find((track) => track.kind === "video");
  const clip =
    video?.clips.find(
      (item) =>
        item.start_seconds <= seconds &&
        seconds < item.start_seconds + item.duration_seconds,
    ) ?? null;
  return {
    ...mockGetTimeline(projectId),
    playhead_seconds: seconds,
    preview: {
      playhead_seconds: seconds,
      duration_seconds: timeline.duration_seconds,
      clip,
      media_url: clip?.media_url ?? null,
      poster_url: clip?.poster_url ?? null,
      scene_id: clip?.scene_id ?? null,
      local_time: clip ? seconds - clip.start_seconds + clip.in_point : null,
    },
  };
}

export function mockEnqueueExport(
  projectId: string,
  aspect: ExportAspect,
): Timeline {
  const timeline = ensureTimeline(projectId);
  timeline.export_queue.push({
    id: `export_${Date.now()}`,
    format: "mp4",
    aspect,
    status: "queued",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message: `Queued mp4 (${aspect})`,
    output_path: null,
  });
  timeline.version += 1;
  return mockGetTimeline(projectId);
}

const mockAudioProjects: Record<string, AudioProject> = {};

function ensureAudio(projectId: string): AudioProject {
  if (!mockAudioProjects[projectId]) {
    const board = mockStoryboards[projectId];
    let cursor = 0;
    const narrations =
      board?.scenes.map((scene) => {
        const duration = scene.duration_seconds || 5;
        const clip = {
          id: `narr_${scene.id}`,
          scene_id: scene.id,
          text: scene.goal || scene.description,
          language: "en",
          voice_profile_id: "voice_mock_1",
          emotion: "neutral",
          speech_rate: 1,
          pitch: 0,
          audio_url: null as string | null,
          duration_seconds: duration,
          start_seconds: cursor,
          status: "draft",
          error: null as string | null,
        };
        cursor += duration;
        return clip;
      }) ?? [];
    mockAudioProjects[projectId] = {
      project_id: projectId,
      version: 1,
      voice_profiles: [
        {
          id: "voice_mock_1",
          character_name: "Napoleon Bonaparte",
          label: "Napoleon voice",
          description: "commanding baritone",
          language: "en",
          emotion: "solemn",
          speech_rate: 1,
          pitch: 0,
          clone_ref: null,
          character_id: "napoleon",
        },
      ],
      narrations,
      music: [],
      sfx: [],
      subtitles: [],
      dubs: [],
      mixer: {
        voice: 1,
        music: 0.35,
        sfx: 0.8,
        master: 1,
        muted_voice: false,
        muted_music: false,
        muted_sfx: false,
      },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
  }
  return mockAudioProjects[projectId];
}

export function mockGetAudio(projectId: string): AudioProject {
  return structuredClone(ensureAudio(projectId));
}

export function mockGenerateNarration(projectId: string): AudioProject {
  const project = ensureAudio(projectId);
  project.narrations = project.narrations.map((clip) => ({
    ...clip,
    status: "generated",
    audio_url: `https://audio.stub.arahus.local/voice-${clip.id}.wav`,
  }));
  project.version += 1;
  return mockGetAudio(projectId);
}

export function mockAudioMusic(projectId: string, mood: string): AudioProject {
  const project = ensureAudio(projectId);
  project.music.push({
    id: `music_${Date.now()}`,
    label: `${mood} bed`,
    mood,
    audio_url: `https://audio.stub.arahus.local/music-${mood}.wav`,
    start_seconds: 0,
    duration_seconds: 30,
    volume: 0.35,
    fade_in_seconds: 1.5,
    fade_out_seconds: 2,
    status: "generated",
  });
  project.version += 1;
  return mockGetAudio(projectId);
}

export function mockAudioSfx(
  projectId: string,
  description: string,
): AudioProject {
  const project = ensureAudio(projectId);
  project.sfx.push({
    id: `sfx_${Date.now()}`,
    label: description.slice(0, 40),
    kind: "scene",
    description,
    audio_url: `https://audio.stub.arahus.local/sfx.wav`,
    start_seconds: 0,
    duration_seconds: 2,
    volume: 0.8,
    status: "generated",
    scene_id: 1,
  });
  project.version += 1;
  return mockGetAudio(projectId);
}

export function mockAutoSubtitles(projectId: string): AudioProject {
  const project = ensureAudio(projectId);
  project.subtitles = project.narrations.map((clip) => ({
    id: `sub_${clip.id}`,
    scene_id: clip.scene_id,
    start_seconds: clip.start_seconds,
    end_seconds: clip.start_seconds + Math.max(clip.duration_seconds, 1),
    text: clip.text,
    language: clip.language,
  }));
  project.version += 1;
  return mockGetAudio(projectId);
}

export function mockSetMixer(
  projectId: string,
  mixer: MixerState,
): AudioProject {
  const project = ensureAudio(projectId);
  project.mixer = mixer;
  project.version += 1;
  return mockGetAudio(projectId);
}

export function mockExportAudioTimeline(projectId: string): {
  audio: AudioProject;
  timeline: Timeline;
} {
  const audio = ensureAudio(projectId);
  const timeline = ensureTimeline(projectId);
  const voice = timeline.tracks.find((track) => track.kind === "voice");
  if (voice) {
    voice.clips = audio.narrations
      .filter((clip) => clip.audio_url)
      .map((clip) => ({
        id: `tl_${clip.id}`,
        label: `Narration ${clip.scene_id}`,
        scene_id: clip.scene_id,
        media_url: clip.audio_url,
        start_seconds: clip.start_seconds,
        duration_seconds: clip.duration_seconds,
        in_point: 0,
        out_point: clip.duration_seconds,
        source_duration: clip.duration_seconds,
        transition_in: "cut" as TransitionType,
        transition_out: "cut" as TransitionType,
        transition_duration: 0,
        muted: false,
        text: clip.text,
        poster_url: null,
        asset_id: null,
      }));
  }
  return { audio: mockGetAudio(projectId), timeline: mockGetTimeline(projectId) };
}

const mockExportStudios: Record<string, ExportStudioState> = {};

const MOCK_PRESETS: ExportPreset[] = [
  {
    id: "youtube_shorts",
    label: "YouTube Shorts",
    aspect: "9:16",
    width: 1080,
    height: 1920,
    fps: 30,
    max_duration_seconds: 60,
    format: "mp4",
    description: "Vertical Shorts up to 60s",
  },
  {
    id: "instagram_reels",
    label: "Instagram Reels",
    aspect: "9:16",
    width: 1080,
    height: 1920,
    fps: 30,
    max_duration_seconds: 90,
    format: "mp4",
    description: "Vertical Reels up to 90s",
  },
  {
    id: "tiktok",
    label: "TikTok",
    aspect: "9:16",
    width: 1080,
    height: 1920,
    fps: 30,
    max_duration_seconds: 180,
    format: "mp4",
    description: "Vertical TikTok up to 3 minutes",
  },
  {
    id: "youtube",
    label: "YouTube",
    aspect: "16:9",
    width: 1920,
    height: 1080,
    fps: 30,
    format: "mp4",
    description: "Landscape YouTube 1080p",
  },
  {
    id: "x",
    label: "X",
    aspect: "1:1",
    width: 1080,
    height: 1080,
    fps: 30,
    max_duration_seconds: 140,
    format: "mp4",
    description: "Square X / Twitter video",
  },
  {
    id: "custom",
    label: "Custom",
    aspect: "16:9",
    width: 1920,
    height: 1080,
    fps: 24,
    format: "mp4",
    description: "User-defined dimensions and format",
  },
];

function ensureExportStudio(projectId: string): ExportStudioState {
  if (!mockExportStudios[projectId]) {
    const now = new Date().toISOString();
    mockExportStudios[projectId] = {
      project_id: projectId,
      version: 1,
      queue: [],
      publishes: [],
      history: [],
      created_at: now,
      updated_at: now,
    };
  }
  return mockExportStudios[projectId];
}

function touchExport(state: ExportStudioState): ExportStudioState {
  state.version += 1;
  state.updated_at = new Date().toISOString();
  return state;
}

export function mockListExportPresets(): ExportPreset[] {
  return MOCK_PRESETS;
}

export function mockListPublishProviders(): PublishProviderHealth[] {
  return (["youtube", "instagram", "tiktok", "x"] as const).map((platform) => ({
    provider: platform,
    platform,
    ready: true,
    live: false,
    oauth: false,
    message: "Stub publisher — OAuth not implemented",
  }));
}

export function mockGetExportStudio(projectId: string): ExportStudioState {
  return structuredClone(ensureExportStudio(projectId));
}

export function mockEnqueueRender(
  projectId: string,
  opts: {
    preset?: ExportPresetId;
    format?: ExportFormat;
    process?: boolean;
  } = {},
): ExportStudioState {
  const state = ensureExportStudio(projectId);
  const preset =
    MOCK_PRESETS.find((p) => p.id === (opts.preset ?? "youtube")) ??
    MOCK_PRESETS[3];
  const format = opts.format ?? preset.format;
  const now = new Date().toISOString();
  const job: RenderJob = {
    id: `render_${Date.now().toString(36)}`,
    project_id: projectId,
    settings: {
      preset: preset.id,
      format,
      aspect: preset.aspect,
      width: preset.width,
      height: preset.height,
      fps: preset.fps,
      include_subtitles: true,
      include_audio: true,
    },
    status: opts.process === false ? "queued" : "ready",
    progress: opts.process === false ? 0 : 1,
    message: opts.process === false ? "Queued" : "Ready",
    attempt: 1,
    max_attempts: 3,
    created_at: now,
    updated_at: now,
    started_at: now,
    finished_at: opts.process === false ? null : now,
    output_path:
      opts.process === false
        ? null
        : `artifacts/projects/${projectId}/exports/mock/output.${format === "image_sequence" ? "seq" : format}`,
    package_path:
      opts.process === false
        ? null
        : `artifacts/projects/${projectId}/exports/mock/package`,
    error: null,
    resumable: true,
  };
  state.queue.push(job);
  if (opts.process !== false) {
    state.history.push({
      id: `hist_${Date.now().toString(36)}`,
      project_id: projectId,
      version: state.history.length + 1,
      render_job_id: job.id,
      settings: job.settings,
      output_path: job.output_path,
      package_path: job.package_path,
      created_at: now,
      message: `v${state.history.length + 1} ${preset.id} ${format}`,
    });
  }
  touchExport(state);
  return mockGetExportStudio(projectId);
}

export function mockExportJobAction(
  projectId: string,
  jobId: string,
  action: "cancel" | "pause" | "resume" | "retry",
): ExportStudioState {
  const state = ensureExportStudio(projectId);
  const job = state.queue.find((item) => item.id === jobId);
  if (!job) throw new Error("Render job not found");
  const now = new Date().toISOString();
  if (action === "cancel") {
    job.status = "cancelled";
    job.message = "Cancelled";
    job.finished_at = now;
  } else if (action === "pause") {
    job.status = "paused";
    job.message = "Paused";
  } else if (action === "resume" || action === "retry") {
    job.status = "ready";
    job.progress = 1;
    job.message = "Ready";
    job.output_path = `artifacts/projects/${projectId}/exports/mock/output.mp4`;
    job.package_path = `artifacts/projects/${projectId}/exports/mock/package`;
    job.finished_at = now;
    if (action === "retry") job.attempt += 1;
  }
  job.updated_at = now;
  touchExport(state);
  return mockGetExportStudio(projectId);
}

export function mockPublish(
  projectId: string,
  body: {
    render_job_id: string;
    platform: PublishPlatform;
    title?: string;
    schedule_at?: string | null;
  },
): ExportStudioState {
  const state = ensureExportStudio(projectId);
  const now = new Date().toISOString();
  const scheduled = Boolean(body.schedule_at);
  const job: PublishJob = {
    id: `publish_${Date.now().toString(36)}`,
    project_id: projectId,
    render_job_id: body.render_job_id,
    platform: body.platform,
    status: scheduled ? "scheduled" : "published",
    title: body.title || `${body.platform} export`,
    description: "",
    tags: [],
    schedule_at: body.schedule_at ?? null,
    created_at: now,
    updated_at: now,
    published_at: scheduled ? null : now,
    external_id: `${body.platform}_mock`,
    external_url: scheduled
      ? null
      : `https://publish.stub.arahus.local/${body.platform}/mock`,
    error: null,
    provider: body.platform,
  };
  state.publishes.push(job);
  for (const entry of state.history) {
    if (entry.render_job_id === body.render_job_id) {
      entry.publish_status = job.status;
      entry.publish_platform = job.platform;
      entry.publish_url = job.external_url;
    }
  }
  touchExport(state);
  return mockGetExportStudio(projectId);
}
