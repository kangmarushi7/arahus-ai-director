"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Redo2, Sparkles, Undo2 } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api/client";
import type { ChatMessage, CopilotPreview } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

function PreviewCard({ preview }: { preview: CopilotPreview }) {
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-accent/30 bg-accent-soft/40 p-3 text-xs">
      <p className="font-medium text-foreground">{preview.summary}</p>
      <ul className="space-y-2">
        {preview.changes.map((change, index) => (
          <li
            key={`${change.type}-${index}`}
            className="rounded-md border border-border bg-card p-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{change.type}</Badge>
              <span>{change.summary}</span>
            </div>
            {change.before || change.after ? (
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <div>
                  <p className="uppercase text-muted-foreground">Before</p>
                  <pre className="mt-1 whitespace-pre-wrap text-[11px] text-muted-foreground">
                    {JSON.stringify(change.before ?? {}, null, 0)}
                  </pre>
                </div>
                <div>
                  <p className="uppercase text-muted-foreground">After</p>
                  <pre className="mt-1 whitespace-pre-wrap text-[11px] text-foreground">
                    {JSON.stringify(
                      change.after ?? change.updates ?? {},
                      null,
                      0,
                    )}
                  </pre>
                </div>
              </div>
            ) : null}
            {change.before_order && change.after_order ? (
              <p className="mt-2 text-muted-foreground">
                Order {change.before_order.join(" → ")} →{" "}
                {change.after_order.join(" → ")}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ChatPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const selectedSceneId = useUiStore((state) => state.selectedSceneId);
  const [draft, setDraft] = useState("");
  const [pendingProposalId, setPendingProposalId] = useState<string | null>(
    null,
  );
  const [pendingPreview, setPendingPreview] = useState<CopilotPreview | null>(
    null,
  );
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const historyQuery = useQuery({
    queryKey: ["chat", projectId],
    queryFn: () => api.getChatHistory(projectId),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [historyQuery.data?.messages.length, pendingPreview]);

  const invalidateStudio = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["storyboard", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["export", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["assets", projectId] }),
    ]);
  };

  const chatMutation = useMutation({
    mutationFn: (message: string) =>
      api.chat(projectId, message, selectedSceneId ?? undefined),
    onSuccess: async (data) => {
      setPendingProposalId(data.proposal_id);
      setPendingPreview(data.preview);
      await queryClient.invalidateQueries({ queryKey: ["chat", projectId] });
    },
  });

  const executeMutation = useMutation({
    mutationFn: () =>
      api.executeChat(projectId, pendingProposalId ?? undefined, false),
    onSuccess: async () => {
      setPendingProposalId(null);
      setPendingPreview(null);
      await invalidateStudio();
    },
  });

  const undoMutation = useMutation({
    mutationFn: () => api.undoChat(projectId),
    onSuccess: async () => {
      await invalidateStudio();
    },
  });

  const redoMutation = useMutation({
    mutationFn: () => api.redoChat(projectId),
    onSuccess: async () => {
      await invalidateStudio();
    },
  });

  const messages: ChatMessage[] = historyQuery.data?.messages ?? [];
  const canUndo = historyQuery.data?.can_undo ?? false;
  const canRedo = historyQuery.data?.can_redo ?? false;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message) return;
    setDraft("");
    chatMutation.mutate(message);
  }

  return (
    <section className="flex h-full min-h-[420px] flex-col rounded-xl border border-border bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-border p-4">
        <div>
          <h3 className="flex items-center gap-2 font-display text-xl">
            <Sparkles className="h-4 w-4 text-accent" />
            AI Copilot
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Edit scenes, media, memory, and order in plain language.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={!canUndo || undoMutation.isPending}
            onClick={() => undoMutation.mutate()}
          >
            <Undo2 className="h-3.5 w-3.5" />
            Undo
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!canRedo || redoMutation.isPending}
            onClick={() => redoMutation.mutate()}
          >
            <Redo2 className="h-3.5 w-3.5" />
            Redo
          </Button>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {!messages.length ? (
          <p className="text-sm text-muted-foreground">
            Try: “set scene 2 lighting to moonlight”, “regenerate image for
            scene 1”, or “reverse the scenes”.
          </p>
        ) : null}
        {messages.map((message) => (
          <div
            key={message.id}
            className={cn(
              "max-w-[95%] rounded-lg px-3 py-2 text-sm",
              message.role === "user"
                ? "ml-auto bg-accent text-accent-foreground"
                : "bg-muted/50 text-foreground",
            )}
          >
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.preview ? <PreviewCard preview={message.preview} /> : null}
          </div>
        ))}
        {pendingPreview && pendingProposalId ? (
          <div className="rounded-lg border border-dashed border-accent p-3">
            <p className="text-sm font-medium">Pending confirmation</p>
            <PreviewCard preview={pendingPreview} />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => executeMutation.mutate()}
                disabled={executeMutation.isPending}
              >
                {executeMutation.isPending ? "Applying…" : "Confirm changes"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setPendingProposalId(null);
                  setPendingPreview(null);
                }}
              >
                Dismiss
              </Button>
            </div>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={onSubmit}
        className="border-t border-border p-3"
      >
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={
              selectedSceneId
                ? `Ask Copilot (scene ${selectedSceneId} selected)…`
                : "Ask Copilot…"
            }
            className="h-10 flex-1 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
          <Button type="submit" disabled={chatMutation.isPending || !draft.trim()}>
            Send
          </Button>
        </div>
      </form>
    </section>
  );
}
