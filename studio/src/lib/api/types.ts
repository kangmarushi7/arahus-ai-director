/** Shared types mirroring the FastAPI contract (Sprint 6.0 / 6.2). */

export type ProjectStatus =
  | "created"
  | "generating"
  | "ready"
  | "failed"
  | string;

export type SceneLifecycle =
  | "draft"
  | "approved"
  | "image_generated"
  | "image_approved"
  | "video_generated"
  | "video_approved"
  | "locked";

export interface Project {
  id: string;
  topic: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  last_run_id?: string | null;
  scene_count: number;
  has_memory: boolean;
  has_storyboard: boolean;
}

export interface ContinuityMeta {
  previous_scene?: string;
  keep?: string[];
  change?: string[];
}

export interface ScenePlan {
  id?: number;
  title?: string;
  description?: string;
  subject?: string;
  environment?: string;
  action?: string;
  camera_shot?: string;
  camera_movement?: string;
  camera_angle?: string;
  lens?: string;
  lighting?: string;
  composition?: string;
  emotion?: string;
  continuity?: string;
  continuity_meta?: ContinuityMeta | null;
  negative_prompt?: string;
}

export interface SceneVersion {
  version: number;
  created_at: string;
  status: SceneLifecycle;
  title?: string;
  description?: string;
  goal?: string;
  image_prompt?: string;
  camera?: string;
  emotion?: string;
  lighting?: string;
  change_summary?: string;
  review_score?: number | null;
}

export interface SceneReview {
  overall_score: number;
  approved: boolean;
  domain_accuracy?: number;
  visual_quality?: number;
  scene_continuity?: number;
  prompt_quality?: number;
  issues?: string[];
  recommendations?: string[];
}

export interface SceneCard {
  id: number;
  title: string;
  description: string;
  goal?: string;
  duration_seconds: number;
  characters: string[];
  location?: string;
  camera?: string;
  emotion?: string;
  lighting?: string;
  image_prompt?: string;
  negative_prompt?: string;
  status: SceneLifecycle;
  version: number;
  versions?: SceneVersion[];
  scene_plan?: ScenePlan | null;
  image?: { url?: string | null; prompt?: string; b64?: string | null } | null;
  video?: {
    url?: string | null;
    duration_seconds?: number | null;
    prompt?: string;
  } | null;
  review?: SceneReview | null;
  review_score?: number | null;
  error?: string | null;
}

export interface Storyboard {
  project_id: string;
  topic: string;
  scenes: SceneCard[];
  status: SceneLifecycle;
  version: number;
  created_at: string;
  updated_at: string;
  review?: SceneReview | null;
}

export interface ScenePatch {
  title?: string;
  description?: string;
  goal?: string;
  camera?: string;
  emotion?: string;
  lighting?: string;
  image_prompt?: string;
  negative_prompt?: string;
  characters?: string[];
  location?: string;
  continuity?: string;
  status?: SceneLifecycle | string;
  duration_seconds?: number;
}

export interface AssetItem {
  id: number;
  kind: string;
  slug: string;
  label: string;
  refs: Record<string, string>;
  metadata: Record<string, unknown>;
}

export interface CostEstimate {
  image_count: number;
  video_count: number;
  scene_ids: number[];
  estimated_gpu_seconds: number;
  estimated_cost_usd: number;
  estimated_gpu_minutes?: number;
}

export interface ProgressEvent {
  type: string;
  project_id: string;
  message?: string;
  fraction?: number | null;
  stages?: Record<string, number>;
  stage_panel?: string;
  payload?: Record<string, unknown>;
}

export interface ApiStatus {
  llm: boolean;
  runpod: boolean;
  r2: boolean;
  database: boolean;
  allow_stubs: boolean;
  ready: boolean;
}

export interface ProjectMemoryExport {
  characters?: Array<{
    name?: string;
    appearance?: string;
    role?: string;
    [key: string]: unknown;
  }>;
  world?: {
    locations?: Array<{ name?: string; description?: string; [key: string]: unknown }>;
    era?: string;
    [key: string]: unknown;
  };
  style?: Record<string, unknown>;
}

export interface ProjectExport {
  project_id: string;
  memory?: ProjectMemoryExport | null;
  storyboard?: Storyboard | null;
}

export interface CopilotChange {
  type: string;
  summary: string;
  scene_id?: number | null;
  updates?: Record<string, unknown>;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  before_order?: number[];
  after_order?: number[];
  target_name?: string | null;
  memory_before?: Record<string, unknown>;
  memory_after?: Record<string, unknown>;
}

export interface CopilotPreview {
  summary: string;
  command_count: number;
  changes: CopilotChange[];
  requires_confirmation?: boolean;
}

export interface CopilotCommand {
  type: string;
  scene_id?: number | null;
  scene_ids?: number[] | null;
  updates?: Record<string, unknown>;
  value?: unknown;
  target_name?: string | null;
  summary?: string;
}

export interface ChatResponse {
  reply: string;
  project_id?: string | null;
  suggestions: string[];
  commands: CopilotCommand[];
  preview: CopilotPreview | null;
  proposal_id: string | null;
  can_undo: boolean;
  can_redo: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  proposal_id?: string | null;
  commands?: CopilotCommand[];
  preview?: CopilotPreview | null;
  executed?: boolean;
}

export interface ChatHistory {
  project_id: string;
  messages: ChatMessage[];
  pending_proposal_id?: string | null;
  can_undo: boolean;
  can_redo: boolean;
}

export type TrackKind = "video" | "voice" | "music" | "sfx" | "subtitles";
export type TransitionType = "cut" | "fade" | "dissolve" | "slide";
export type ExportAspect = "16:9" | "9:16" | "1:1";

export interface TimelineClip {
  id: string;
  label: string;
  scene_id?: number | null;
  asset_id?: number | null;
  media_url?: string | null;
  poster_url?: string | null;
  start_seconds: number;
  duration_seconds: number;
  in_point: number;
  out_point: number;
  source_duration: number;
  transition_in: TransitionType;
  transition_out: TransitionType;
  transition_duration: number;
  muted: boolean;
  text?: string | null;
}

export interface TimelineTrack {
  id: string;
  kind: TrackKind;
  name: string;
  clips: TimelineClip[];
  locked: boolean;
  muted: boolean;
  height: number;
}

export interface ExportJob {
  id: string;
  format: "mp4";
  aspect: ExportAspect;
  status: "queued" | "processing" | "ready" | "failed";
  created_at: string;
  updated_at: string;
  message: string;
  output_path?: string | null;
}

export interface Timeline {
  project_id: string;
  version: number;
  tracks: TimelineTrack[];
  export_queue: ExportJob[];
  playhead_seconds: number;
  duration_seconds: number;
  created_at: string;
  updated_at: string;
  preview?: TimelinePreview | null;
}

export interface TimelinePreview {
  playhead_seconds: number;
  duration_seconds: number;
  clip?: TimelineClip | null;
  media_url?: string | null;
  poster_url?: string | null;
  scene_id?: number | null;
  local_time?: number | null;
}

export interface VoiceProfile {
  id: string;
  character_id?: string | null;
  character_name: string;
  label: string;
  description: string;
  language: string;
  emotion: string;
  speech_rate: number;
  pitch: number;
  clone_ref?: string | null;
}

export interface NarrationClip {
  id: string;
  scene_id?: number | null;
  text: string;
  language: string;
  voice_profile_id?: string | null;
  emotion: string;
  speech_rate: number;
  pitch: number;
  audio_url?: string | null;
  duration_seconds: number;
  start_seconds: number;
  status: string;
  error?: string | null;
}

export interface MusicBed {
  id: string;
  label: string;
  mood: string;
  audio_url?: string | null;
  start_seconds: number;
  duration_seconds: number;
  volume: number;
  fade_in_seconds: number;
  fade_out_seconds: number;
  status: string;
}

export interface SfxCue {
  id: string;
  label: string;
  kind: string;
  scene_id?: number | null;
  description: string;
  audio_url?: string | null;
  start_seconds: number;
  duration_seconds: number;
  volume: number;
  status: string;
}

export interface SubtitleCue {
  id: string;
  scene_id?: number | null;
  start_seconds: number;
  end_seconds: number;
  text: string;
  language: string;
}

export interface DubTrack {
  id: string;
  language: string;
  label: string;
  voice_map: Record<string, string>;
  narration_ids: string[];
  synced: boolean;
}

export interface MixerState {
  voice: number;
  music: number;
  sfx: number;
  master: number;
  muted_voice: boolean;
  muted_music: boolean;
  muted_sfx: boolean;
}

export interface AudioProject {
  project_id: string;
  version: number;
  voice_profiles: VoiceProfile[];
  narrations: NarrationClip[];
  music: MusicBed[];
  sfx: SfxCue[];
  subtitles: SubtitleCue[];
  dubs: DubTrack[];
  mixer: MixerState;
  created_at: string;
  updated_at: string;
}

export type ExportFormat = "mp4" | "mov" | "gif" | "image_sequence";
export type ExportPresetId =
  | "youtube_shorts"
  | "instagram_reels"
  | "tiktok"
  | "youtube"
  | "x"
  | "custom";
export type RenderJobStatus =
  | "queued"
  | "processing"
  | "ready"
  | "failed"
  | "cancelled"
  | "paused";
export type PublishPlatform = "youtube" | "instagram" | "tiktok" | "x";
export type PublishStatus =
  | "draft"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed"
  | "cancelled";

export interface ExportPreset {
  id: ExportPresetId;
  label: string;
  aspect: string;
  width: number;
  height: number;
  fps: number;
  max_duration_seconds?: number | null;
  format: ExportFormat;
  description: string;
}

export interface ExportSettings {
  preset: ExportPresetId;
  format: ExportFormat;
  aspect: string;
  width: number;
  height: number;
  fps: number;
  include_subtitles: boolean;
  include_audio: boolean;
  custom_label?: string | null;
}

export interface RenderJob {
  id: string;
  project_id: string;
  settings: ExportSettings;
  status: RenderJobStatus;
  progress: number;
  message: string;
  attempt: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  output_path?: string | null;
  package_path?: string | null;
  error?: string | null;
  resumable: boolean;
}

export interface PublishJob {
  id: string;
  project_id: string;
  render_job_id: string;
  platform: PublishPlatform;
  status: PublishStatus;
  title: string;
  description: string;
  tags: string[];
  schedule_at?: string | null;
  created_at: string;
  updated_at: string;
  published_at?: string | null;
  external_id?: string | null;
  external_url?: string | null;
  error?: string | null;
  provider: string;
}

export interface ExportHistoryEntry {
  id: string;
  project_id: string;
  version: number;
  render_job_id: string;
  settings: ExportSettings;
  output_path?: string | null;
  package_path?: string | null;
  publish_status?: PublishStatus | null;
  publish_platform?: PublishPlatform | null;
  publish_url?: string | null;
  created_at: string;
  message: string;
}

export interface ExportStudioState {
  project_id: string;
  version: number;
  queue: RenderJob[];
  publishes: PublishJob[];
  history: ExportHistoryEntry[];
  created_at: string;
  updated_at: string;
}

export interface PublishProviderHealth {
  provider: string;
  platform: string;
  ready: boolean;
  live: boolean;
  oauth: boolean;
  message: string;
}
