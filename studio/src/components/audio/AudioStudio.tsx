"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic2, Music2, Subtitles, Volume2, Waves } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { AudioProject, MixerState } from "@/lib/api/types";
import { titleCase } from "@/lib/utils";

const MOODS = [
  "epic",
  "somber",
  "tense",
  "hopeful",
  "mysterious",
  "triumphant",
  "ambient",
] as const;

function MixerSlider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block text-sm">
      <div className="mb-1 flex justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span>{Math.round(value * 100)}%</span>
      </div>
      <input
        type="range"
        min={0}
        max={2}
        step={0.05}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-[var(--accent)]"
      />
    </label>
  );
}

export function AudioStudio({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [sfxText, setSfxText] = useState("wind over alpine ridge");

  const audioQuery = useQuery({
    queryKey: ["audio", projectId],
    queryFn: () => api.getAudio(projectId),
  });

  const setAudio = (audio: AudioProject) => {
    queryClient.setQueryData(["audio", projectId], audio);
  };

  const mutate = useMutation({
    mutationFn: async (action: () => Promise<AudioProject>) => action(),
    onSuccess: setAudio,
  });

  const exportMutation = useMutation({
    mutationFn: () => api.exportAudioTimeline(projectId),
    onSuccess: (result) => {
      setAudio(result.audio);
      queryClient.setQueryData(["timeline", projectId], result.timeline);
    },
  });

  const audio = audioQuery.data;
  const mixer: MixerState = audio?.mixer ?? {
    voice: 1,
    music: 0.35,
    sfx: 0.8,
    master: 1,
    muted_voice: false,
    muted_music: false,
    muted_sfx: false,
  };

  if (audioQuery.isLoading && !audio) {
    return <p className="text-muted-foreground">Loading audio studio…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => mutate.mutate(() => api.generateNarration(projectId))}
          disabled={mutate.isPending}
        >
          <Mic2 className="h-3.5 w-3.5" />
          Generate narration
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => mutate.mutate(() => api.autoSubtitles(projectId))}
        >
          <Subtitles className="h-3.5 w-3.5" />
          Auto subtitles
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => exportMutation.mutate()}
          disabled={exportMutation.isPending}
        >
          Export to timeline
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-xl border border-border bg-card p-4">
          <h3 className="flex items-center gap-2 font-display text-xl">
            <Mic2 className="h-4 w-4 text-accent" />
            Voice profiles
          </h3>
          <ul className="mt-3 space-y-2">
            {(audio?.voice_profiles ?? []).map((profile) => (
              <li
                key={profile.id}
                className="rounded-lg border border-border px-3 py-2 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    {profile.label || profile.character_name}
                  </span>
                  <Badge>{titleCase(profile.emotion)}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  rate {profile.speech_rate} · pitch {profile.pitch} ·{" "}
                  {profile.language}
                  {profile.clone_ref ? ` · clone ${profile.clone_ref}` : ""}
                </p>
              </li>
            ))}
            {!audio?.voice_profiles?.length ? (
              <li className="text-sm text-muted-foreground">
                No voices yet — seeded from character memory when available.
              </li>
            ) : null}
          </ul>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h3 className="flex items-center gap-2 font-display text-xl">
            <Volume2 className="h-4 w-4 text-accent" />
            Audio mixer
          </h3>
          <div className="mt-4 space-y-3">
            <MixerSlider
              label="Voice"
              value={mixer.voice}
              onChange={(voice) =>
                mutate.mutate(() =>
                  api.setMixer(projectId, { ...mixer, voice }),
                )
              }
            />
            <MixerSlider
              label="Music"
              value={mixer.music}
              onChange={(music) =>
                mutate.mutate(() =>
                  api.setMixer(projectId, { ...mixer, music }),
                )
              }
            />
            <MixerSlider
              label="SFX"
              value={mixer.sfx}
              onChange={(sfx) =>
                mutate.mutate(() => api.setMixer(projectId, { ...mixer, sfx }))
              }
            />
            <MixerSlider
              label="Master"
              value={mixer.master}
              onChange={(master) =>
                mutate.mutate(() =>
                  api.setMixer(projectId, { ...mixer, master }),
                )
              }
            />
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h3 className="font-display text-xl">Narration</h3>
          <ul className="mt-3 max-h-72 space-y-2 overflow-y-auto">
            {(audio?.narrations ?? []).map((clip) => (
              <li
                key={clip.id}
                className="rounded-lg border border-border px-3 py-2 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span>Scene {clip.scene_id ?? "—"}</span>
                  <Badge>{titleCase(clip.status)}</Badge>
                </div>
                <p className="mt-1 line-clamp-2 text-muted-foreground">
                  {clip.text}
                </p>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h3 className="flex items-center gap-2 font-display text-xl">
            <Music2 className="h-4 w-4 text-accent" />
            Music & SFX
          </h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {MOODS.map((mood) => (
              <Button
                key={mood}
                size="sm"
                variant="secondary"
                onClick={() =>
                  mutate.mutate(() => api.addMusic(projectId, mood))
                }
              >
                {titleCase(mood)}
              </Button>
            ))}
          </div>
          <div className="mt-4 flex gap-2">
            <input
              value={sfxText}
              onChange={(event) => setSfxText(event.target.value)}
              className="h-10 flex-1 rounded-lg border border-border bg-background px-3 text-sm"
              placeholder="SFX description"
            />
            <Button
              size="sm"
              onClick={() =>
                mutate.mutate(() => api.addSfx(projectId, sfxText))
              }
            >
              <Waves className="h-3.5 w-3.5" />
              Add SFX
            </Button>
          </div>
          <ul className="mt-4 space-y-2 text-sm">
            {(audio?.music ?? []).map((bed) => (
              <li key={bed.id} className="flex justify-between gap-2">
                <span>
                  Music · {titleCase(bed.mood)} · fade {bed.fade_in_seconds}/
                  {bed.fade_out_seconds}s
                </span>
                <Badge>{titleCase(bed.status)}</Badge>
              </li>
            ))}
            {(audio?.sfx ?? []).map((cue) => (
              <li key={cue.id} className="flex justify-between gap-2">
                <span>
                  {titleCase(cue.kind)} · {cue.label}
                </span>
                <Badge>{titleCase(cue.status)}</Badge>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-xl border border-border bg-card p-4 xl:col-span-2">
          <h3 className="flex items-center gap-2 font-display text-xl">
            <Subtitles className="h-4 w-4 text-accent" />
            Subtitles & dubbing
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Auto-generated cues are editable. Export SRT/VTT via API. Dub tracks
            map voices per language and sync to timeline timing.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <ul className="max-h-56 space-y-2 overflow-y-auto">
              {(audio?.subtitles ?? []).map((cue) => (
                <li
                  key={cue.id}
                  className="rounded-lg border border-border px-3 py-2 text-sm"
                >
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>
                      {cue.start_seconds.toFixed(1)}s → {cue.end_seconds.toFixed(1)}s
                    </span>
                    <span>{cue.language}</span>
                  </div>
                  <p className="mt-1">{cue.text}</p>
                </li>
              ))}
              {!audio?.subtitles?.length ? (
                <li className="text-sm text-muted-foreground">
                  No subtitles yet — run Auto subtitles.
                </li>
              ) : null}
            </ul>
            <ul className="space-y-2">
              {(audio?.dubs ?? []).map((dub) => (
                <li
                  key={dub.id}
                  className="rounded-lg border border-border px-3 py-2 text-sm"
                >
                  <div className="flex justify-between">
                    <span>{dub.label || dub.language}</span>
                    <Badge>{dub.synced ? "Synced" : "Draft"}</Badge>
                  </div>
                </li>
              ))}
              {!audio?.dubs?.length ? (
                <li className="text-sm text-muted-foreground">
                  Add dubs via API: POST /audio/dubs with language + voice_map.
                </li>
              ) : null}
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
}
