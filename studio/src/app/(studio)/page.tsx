"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Plus } from "lucide-react";
import { FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api/client";
import { titleCase } from "@/lib/utils";

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const [topic, setTopic] = useState("");
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
  });
  const statusQuery = useQuery({
    queryKey: ["api-status"],
    queryFn: () => api.getStatus(),
  });

  const createMutation = useMutation({
    mutationFn: (value: string) => api.createProject(value),
    onSuccess: async () => {
      setTopic("");
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  function onCreate(event: FormEvent) {
    event.preventDefault();
    const cleaned = topic.trim();
    if (!cleaned) return;
    createMutation.mutate(cleaned);
  }

  const projects = projectsQuery.data ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="space-y-3">
        <p className="text-sm uppercase tracking-[0.2em] text-accent">
          Dashboard
        </p>
        <h1 className="font-display text-5xl text-foreground md:text-6xl">
          Arahus
        </h1>
        <p className="max-w-2xl text-base text-muted-foreground md:text-lg">
          Plan cinematic scenes, approve storyboards, and generate images and
          videos with full creative control.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
        <form
          onSubmit={onCreate}
          className="rounded-xl border border-border bg-card p-5"
        >
          <h2 className="font-display text-2xl">New project</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Start from a topic. The FastAPI backend creates the project and
            storyboard workflow.
          </p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="Napoleon crossing the Alps"
              className="h-11 flex-1 rounded-lg border border-border bg-background px-3 text-sm outline-none ring-accent focus:ring-2"
            />
            <Button type="submit" disabled={createMutation.isPending}>
              <Plus className="h-4 w-4" />
              Create
            </Button>
          </div>
        </form>

        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-display text-2xl">Backend</h2>
          <ul className="mt-4 space-y-2 text-sm">
            {Object.entries(statusQuery.data ?? {}).map(([key, value]) => (
              <li key={key} className="flex items-center justify-between">
                <span className="text-muted-foreground">{titleCase(key)}</span>
                <Badge
                  className={
                    value
                      ? "border-success/30 bg-success/10 text-success"
                      : "border-border"
                  }
                >
                  {value ? "ready" : "off"}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section>
        <div className="mb-4 flex items-end justify-between">
          <h2 className="font-display text-3xl">Projects</h2>
          <p className="text-sm text-muted-foreground">{projects.length} total</p>
        </div>
        <div className="grid gap-3">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/projects/${project.id}`}
              className="group flex flex-col gap-2 rounded-xl border border-border bg-card p-4 transition hover:border-accent/50 sm:flex-row sm:items-center sm:justify-between"
            >
              <div>
                <h3 className="font-display text-2xl group-hover:text-accent">
                  {project.topic}
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">{project.id}</p>
              </div>
              <div className="flex items-center gap-3">
                <Badge>{titleCase(project.status)}</Badge>
                <Badge>{project.scene_count} scenes</Badge>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground" />
              </div>
            </Link>
          ))}
          {!projects.length ? (
            <p className="rounded-xl border border-dashed border-border p-8 text-center text-muted-foreground">
              No projects yet.
            </p>
          ) : null}
        </div>
      </section>
    </div>
  );
}
