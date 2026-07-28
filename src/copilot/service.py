"""Copilot orchestration: parse → preview → execute → undo/redo."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from src.copilot.commands import CommandProposal, CopilotCommand
from src.copilot.executor import CopilotExecutor, clone_board, clone_memory
from src.copilot.history import ChatHistory, ChatHistoryStore, ChatMessage
from src.copilot.parser import parse_intent
from src.copilot.preview import build_preview
from src.copilot.undo import UndoEntry, UndoStore
from src.memory.store import ProjectMemoryStore
from src.models.memory import ProjectMemory
from src.studio.models import Storyboard
from src.studio.service import StoryboardStudio
from src.studio.store import StoryboardStore


class CopilotService:
    """Natural-language project editor over StoryboardStudio + memory."""

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        studio: StoryboardStudio | None = None,
        memory_store: ProjectMemoryStore | None = None,
        history_store: ChatHistoryStore | None = None,
        undo_store: UndoStore | None = None,
        executor: CopilotExecutor | None = None,
    ) -> None:
        root_path = Path(root) if root is not None else Path("artifacts") / "projects"
        self._root = root_path
        self._studio = studio or StoryboardStudio(store=StoryboardStore(root=root_path))
        self._memory = memory_store or ProjectMemoryStore(root=root_path)
        self._history = history_store or ChatHistoryStore(root=root_path)
        self._undo = undo_store or UndoStore(root=root_path)
        self._executor = executor or CopilotExecutor(self._studio)
        self._proposals: dict[str, CommandProposal] = {}

    @property
    def studio(self) -> StoryboardStudio:
        return self._studio

    def history(self, project_id: str) -> ChatHistory:
        return self._history.load(project_id)

    def can_undo(self, project_id: str) -> bool:
        return bool(self._undo.load(project_id).undo_stack)

    def can_redo(self, project_id: str) -> bool:
        return bool(self._undo.load(project_id).redo_stack)

    def propose(
        self,
        project_id: str,
        message: str,
        *,
        selected_scene_id: int | None = None,
    ) -> dict[str, Any]:
        board = self._studio.load(project_id)
        memory = self._memory.load(project_id)
        commands = parse_intent(
            message,
            storyboard=board,
            selected_scene_id=selected_scene_id,
        )

        needs_memory = any(
            c.type.value.startswith("modify_") for c in commands
        )
        if needs_memory and memory is None:
            memory = ProjectMemory(project_id=project_id, topic=project_id)

        self._history.append(
            project_id,
            ChatMessage(role="user", content=message),
        )

        if not commands:
            reply = (
                "I couldn't map that to a studio command. Try things like "
                "'set scene 2 lighting to moonlight', 'regenerate image for scene 1', "
                "'reorder scenes 4,1,2,3', or 'change style to painterly'."
            )
            self._history.append(
                project_id,
                ChatMessage(role="assistant", content=reply),
                pending_proposal_id=None,
            )
            return {
                "reply": reply,
                "project_id": project_id,
                "suggestions": [
                    "set scene 1 camera to close-up dolly",
                    "change lighting on scene 2 to golden hour",
                    "regenerate image for scene 3",
                    "reverse the scenes",
                    "set duration of scene 2 to 8 seconds",
                ],
                "commands": [],
                "preview": None,
                "proposal_id": None,
                "can_undo": self.can_undo(project_id),
                "can_redo": self.can_redo(project_id),
            }

        # Simulate without persisting for preview.
        sim_board = clone_board(board)
        sim_memory = clone_memory(memory)
        try:
            sim_board, sim_memory, _ = self._executor.apply(
                commands,
                storyboard=sim_board,
                memory=sim_memory,
                persist=False,
                run_media=False,
            )
        except Exception as exc:  # noqa: BLE001 - surface as chat reply
            reply = f"Could not preview that change: {exc}"
            self._history.append(
                project_id,
                ChatMessage(role="assistant", content=reply),
            )
            return {
                "reply": reply,
                "project_id": project_id,
                "suggestions": [],
                "commands": [c.model_dump(mode="json") for c in commands],
                "preview": None,
                "proposal_id": None,
                "can_undo": self.can_undo(project_id),
                "can_redo": self.can_redo(project_id),
            }

        preview = build_preview(
            commands,
            storyboard=board,
            memory=memory,
            simulated_board=sim_board,
            simulated_memory=sim_memory,
        )
        proposal_id = uuid.uuid4().hex[:12]
        proposal = CommandProposal(
            proposal_id=proposal_id,
            project_id=project_id,
            message=message,
            reply=f"Proposed {len(commands)} change(s). Review the preview, then confirm.",
            commands=commands,
            status="pending",
        )
        self._proposals[proposal_id] = proposal
        # Persist pending proposal id on history for confirm-after-reload.
        self._persist_proposal(proposal)

        reply = proposal.reply + " " + preview["summary"]
        self._history.append(
            project_id,
            ChatMessage(
                role="assistant",
                content=reply,
                proposal_id=proposal_id,
                commands=[c.model_dump(mode="json") for c in commands],
                preview=preview,
            ),
            pending_proposal_id=proposal_id,
        )
        return {
            "reply": reply,
            "project_id": project_id,
            "suggestions": ["Confirm with POST /chat/execute", "Or refine your request"],
            "commands": [c.model_dump(mode="json") for c in commands],
            "preview": preview,
            "proposal_id": proposal_id,
            "can_undo": self.can_undo(project_id),
            "can_redo": self.can_redo(project_id),
        }

    def execute(
        self,
        project_id: str,
        *,
        proposal_id: str | None = None,
        run_media: bool = True,
    ) -> dict[str, Any]:
        proposal = self._resolve_proposal(project_id, proposal_id)
        if proposal is None:
            raise KeyError("No pending proposal to execute")
        if proposal.status != "pending":
            raise ValueError(f"Proposal {proposal.proposal_id} is {proposal.status}")

        board = self._studio.load(project_id)
        memory = self._memory.load(project_id)
        needs_memory = any(
            c.type.value.startswith("modify_") for c in proposal.commands
        )
        if needs_memory and memory is None:
            memory = ProjectMemory(project_id=project_id, topic=project_id)
        before_board = board.to_dict() if board else None
        before_memory = memory.to_dict() if memory else None

        board_out, memory_out, notes = self._executor.apply(
            proposal.commands,
            storyboard=board,
            memory=memory,
            persist=True,
            run_media=run_media,
        )
        if memory_out is not None:
            after_mem = memory_out.to_dict()
            if before_memory != after_mem:
                self._memory.save(memory_out)

        after_board = board_out.to_dict() if board_out else None
        after_memory = memory_out.to_dict() if memory_out else None

        entry = UndoEntry(
            project_id=project_id,
            proposal_id=proposal.proposal_id,
            label="; ".join(notes) or proposal.reply,
            before_storyboard=before_board,
            after_storyboard=after_board,
            before_memory=before_memory,
            after_memory=after_memory,
        )
        self._undo.push(entry)

        proposal = proposal.model_copy(update={"status": "executed"})
        self._proposals[proposal.proposal_id] = proposal
        self._persist_proposal(proposal)

        history = self._history.load(project_id)
        history.pending_proposal_id = None
        for index, msg in enumerate(history.messages):
            if msg.proposal_id == proposal.proposal_id:
                history.messages[index] = msg.model_copy(update={"executed": True})
        history.messages.append(
            ChatMessage(
                role="assistant",
                content=f"Executed: {entry.label}",
                proposal_id=proposal.proposal_id,
                executed=True,
            )
        )
        self._history.save(history)

        return {
            "reply": f"Executed: {entry.label}",
            "project_id": project_id,
            "proposal_id": proposal.proposal_id,
            "commands": [c.model_dump(mode="json") for c in proposal.commands],
            "storyboard": after_board,
            "can_undo": True,
            "can_redo": False,
            "notes": notes,
        }

    def undo(self, project_id: str) -> dict[str, Any]:
        state = self._undo.load(project_id)
        if not state.undo_stack:
            raise KeyError("Nothing to undo")
        entry = state.undo_stack.pop()
        self._restore(entry, direction="before")
        state.redo_stack.append(entry)
        self._undo.save(state)
        reply = f"Undid: {entry.label}"
        self._history.append(
            project_id,
            ChatMessage(role="system", content=reply),
        )
        return {
            "reply": reply,
            "project_id": project_id,
            "can_undo": bool(state.undo_stack),
            "can_redo": True,
            "entry_id": entry.id,
        }

    def redo(self, project_id: str) -> dict[str, Any]:
        state = self._undo.load(project_id)
        if not state.redo_stack:
            raise KeyError("Nothing to redo")
        entry = state.redo_stack.pop()
        self._restore(entry, direction="after")
        state.undo_stack.append(entry)
        self._undo.save(state)
        reply = f"Redid: {entry.label}"
        self._history.append(
            project_id,
            ChatMessage(role="system", content=reply),
        )
        return {
            "reply": reply,
            "project_id": project_id,
            "can_undo": True,
            "can_redo": bool(state.redo_stack),
            "entry_id": entry.id,
        }

    def _restore(self, entry: UndoEntry, *, direction: str) -> None:
        board_payload = (
            entry.before_storyboard
            if direction == "before"
            else entry.after_storyboard
        )
        memory_payload = (
            entry.before_memory if direction == "before" else entry.after_memory
        )
        if board_payload is not None:
            self._studio.save(Storyboard.from_dict(board_payload))
        if memory_payload is not None:
            self._memory.save(ProjectMemory.from_dict(memory_payload))

    def _resolve_proposal(
        self, project_id: str, proposal_id: str | None
    ) -> CommandProposal | None:
        if proposal_id and proposal_id in self._proposals:
            return self._proposals[proposal_id]
        history = self._history.load(project_id)
        pid = proposal_id or history.pending_proposal_id
        if not pid:
            return None
        if pid in self._proposals:
            return self._proposals[pid]
        # Rebuild from history message.
        for msg in reversed(history.messages):
            if msg.proposal_id == pid and msg.commands:
                commands = [CopilotCommand.model_validate(c) for c in msg.commands]
                proposal = CommandProposal(
                    proposal_id=pid,
                    project_id=project_id,
                    message="",
                    reply=msg.content,
                    commands=commands,
                    status="executed" if msg.executed else "pending",
                )
                self._proposals[pid] = proposal
                return proposal
        return self._load_proposal_file(project_id, pid)

    def _proposal_path(self, project_id: str, proposal_id: str) -> Path:
        safe = project_id.replace("..", "_").replace("/", "_").replace("\\", "_")
        return self._root / safe / "copilot_proposals" / f"{proposal_id}.json"

    def _persist_proposal(self, proposal: CommandProposal) -> None:
        path = self._proposal_path(proposal.project_id, proposal.proposal_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")

    def _load_proposal_file(
        self, project_id: str, proposal_id: str
    ) -> CommandProposal | None:
        path = self._proposal_path(project_id, proposal_id)
        if not path.is_file():
            return None
        proposal = CommandProposal.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        self._proposals[proposal_id] = proposal
        return proposal
