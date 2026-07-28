# Arahus Studio (Next.js 15)

Production UI for Arahus AI Director.

## Stack

- Next.js 15 + TypeScript
- Tailwind CSS v4
- shadcn-style Radix primitives
- TanStack Query
- Zustand

## Develop

```bash
cd studio
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Connect to FastAPI

```bash
# studio/.env.local
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_USE_MOCKS=false
```

When the API URL is empty or `NEXT_PUBLIC_USE_MOCKS=true`, the UI falls back to
local mock projects / storyboards / assets.

On Railway / Docker production builds, the Studio uses same-origin
`NEXT_PUBLIC_API_URL=/backend` (Caddy strips `/backend` to the FastAPI API).

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard |
| `/projects/[id]` | Project overview + generate |
| `/projects/[id]/storyboard` | Interactive canvas, inspector, media |
| `/assets` | Asset library (images / videos / characters / worlds) |
| `/settings` | API connection |

## Interactive Studio (Sprint 6.2)

- **Storyboard canvas** — drag-and-drop scene order (`PUT …/storyboard/order`)
- **Scene inspector** — camera, lighting, emotion, prompt, character, world, continuity
- **Media panel** — image/video preview, generate / regenerate, version compare
- **Progress** — WebSocket `/ws/projects/{id}` with stage, ETA, cost, GPU
- **Asset browser** — filtered registry browser

## AI Copilot (Sprint 6.3)

Natural-language editing via `ChatPanel` on the storyboard page.

| Action | Endpoint |
|--------|----------|
| Propose + preview | `POST /chat` |
| Confirm execute | `POST /chat/execute` |
| Undo / redo | `POST /chat/undo`, `POST /chat/redo` |
| History | `GET /projects/{id}/chat` |

Supports edit scene, regenerate image/video, modify character/world/style,
reorder, duration, camera/lighting/emotion — all through existing Studio APIs.

## Timeline Editor (Sprint 6.4)

Non-destructive multi-track editor at `/projects/[id]/timeline`.

- Tracks: Video · Voice · Music · SFX · Subtitles
- Edit: drag reorder, resize duration, trim, split, merge, delete, duplicate
- Transitions: cut · fade · dissolve · slide
- Live preview with playhead / frame seek (existing assets only)
- Export queue: MP4 · 16:9 · 9:16 · 1:1
- Persisted at `artifacts/projects/{id}/timeline.json`

## Voice & Audio Studio (Sprint 6.5)

Provider-agnostic audio at `/projects/[id]/audio`.

- Voice profiles (emotion, rate, pitch, clone_ref)
- Scene / project narration via `AudioRouter` (stub by default)
- Mood music + ambient/scene SFX
- Subtitles (auto, editable, SRT/VTT export)
- Dubbing with voice mapping + timeline sync
- Mixer (voice / music / SFX / master)
- Export integrated audio onto timeline tracks

No ElevenLabs (or other vendor) hardcoding — adapters register by YAML `type`.

## Components

`Sidebar`, `StoryboardCanvas`, `SceneCard`, `SceneInspector`, `MediaPanel`,
`ChatPanel`, `TimelineEditor`, `AudioStudio`, `ImageViewer`, `VideoPlayer`,
`ProgressPanel`, `ReviewBadge`, `CostEstimate`, `AssetBrowser`


