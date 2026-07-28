"""Rule-based natural-language → structured CopilotCommand parser.

Deterministic for tests and offline Studio use. Optional JSON override:
``{"commands": [...]}`` in the message body.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.copilot.commands import CommandType, CopilotCommand
from src.studio.models import Storyboard

_SCENE_RE = re.compile(
    r"\bscene\s*(?:#|number\s*)?(\d+)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(?:duration|length|runtime).{0,40}?\bto\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)?\b",
    re.IGNORECASE,
)
_DURATION_ALT_RE = re.compile(
    r"(?:set|make|change).{0,40}?(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b",
    re.IGNORECASE,
)
_DURATION_OF_SCENE_RE = re.compile(
    r"scene\s*(\d+).{0,20}?(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b",
    re.IGNORECASE,
)
_REORDER_LIST_RE = re.compile(
    r"reorder(?:\s+scenes?)?\s*(?:to|=|:)?\s*([0-9,\s→\->]+)",
    re.IGNORECASE,
)
_MOVE_BEFORE_RE = re.compile(
    r"move\s+scene\s*(\d+)\s+before\s+scene\s*(\d+)",
    re.IGNORECASE,
)
_SWAP_RE = re.compile(
    r"swap\s+scene\s*(\d+)\s+(?:and|with)\s+scene\s*(\d+)",
    re.IGNORECASE,
)


def _scene_id(message: str, default: int | None = None) -> int | None:
    match = _SCENE_RE.search(message)
    if match:
        return int(match.group(1))
    return default


def _clean_value(value: str | None) -> str | None:
    if not value:
        return value
    cleaned = re.sub(
        r"^on\s+scene\s*\d+\s*(?:to\s*)?",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" :,")
    return " ".join(cleaned.split()) or None


def _quoted_or_after(message: str, keywords: tuple[str, ...]) -> str | None:
    lower = message.casefold()
    for key in keywords:
        idx = lower.find(key)
        if idx < 0:
            continue
        rest = message[idx + len(key) :].strip(" :-=\"'")
        # Stop at sentence boundary / conjunctions that start a new intent.
        cut = re.split(r"[.;\n]|,\s*(?:and|then)\s+", rest, maxsplit=1)[0]
        value = cut.strip(" .,\"'")
        if value:
            return _clean_value(" ".join(value.split()))
    return None


def _try_json_commands(message: str) -> list[CopilotCommand] | None:
    text = message.strip()
    if not (text.startswith("{") or text.startswith("[")):
        # Allow trailing JSON block.
        brace = text.find("{")
        if brace < 0:
            return None
        text = text[brace:]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    raw_list: list[Any]
    if isinstance(payload, dict) and "commands" in payload:
        raw_list = list(payload["commands"])
    elif isinstance(payload, list):
        raw_list = payload
    elif isinstance(payload, dict) and "type" in payload:
        raw_list = [payload]
    else:
        return None
    return [CopilotCommand.model_validate(item) for item in raw_list]


def parse_intent(
    message: str,
    *,
    storyboard: Storyboard | None = None,
    selected_scene_id: int | None = None,
) -> list[CopilotCommand]:
    """Parse user text into zero or more structured commands."""
    json_cmds = _try_json_commands(message)
    if json_cmds is not None:
        return json_cmds

    text = " ".join(message.split())
    lower = text.casefold()
    commands: list[CopilotCommand] = []
    scene = _scene_id(text, selected_scene_id)

    # --- reorder ---
    move = _MOVE_BEFORE_RE.search(text)
    if move and storyboard is not None:
        moving = int(move.group(1))
        before = int(move.group(2))
        order = [s.id for s in storyboard.scenes]
        if moving in order and before in order:
            order.remove(moving)
            order.insert(order.index(before), moving)
            commands.append(
                CopilotCommand(
                    type=CommandType.REORDER_SCENES,
                    scene_ids=order,
                    summary=f"Move scene {moving} before scene {before}",
                )
            )
            return commands

    swap = _SWAP_RE.search(text)
    if swap and storyboard is not None:
        a, b = int(swap.group(1)), int(swap.group(2))
        order = [s.id for s in storyboard.scenes]
        if a in order and b in order:
            ia, ib = order.index(a), order.index(b)
            order[ia], order[ib] = order[ib], order[ia]
            commands.append(
                CopilotCommand(
                    type=CommandType.REORDER_SCENES,
                    scene_ids=order,
                    summary=f"Swap scenes {a} and {b}",
                )
            )
            return commands

    reorder = _REORDER_LIST_RE.search(text)
    if reorder or "reverse scenes" in lower or "reverse the scenes" in lower:
        if storyboard is not None and (
            "reverse scenes" in lower or "reverse the scenes" in lower
        ):
            order = list(reversed([s.id for s in storyboard.scenes]))
            commands.append(
                CopilotCommand(
                    type=CommandType.REORDER_SCENES,
                    scene_ids=order,
                    summary="Reverse scene order",
                )
            )
            return commands
        if reorder:
            nums = [int(n) for n in re.findall(r"\d+", reorder.group(1))]
            if nums:
                commands.append(
                    CopilotCommand(
                        type=CommandType.REORDER_SCENES,
                        scene_ids=nums,
                        summary=f"Reorder scenes to {nums}",
                    )
                )
                return commands

    # --- regenerate media ---
    if any(
        phrase in lower
        for phrase in (
            "regenerate image",
            "regen image",
            "re-generate image",
            "generate image",
            "rerender image",
            "re-render image",
        )
    ):
        if scene is None:
            return []
        commands.append(
            CopilotCommand(
                type=CommandType.REGENERATE_IMAGE,
                scene_id=scene,
                summary=f"Regenerate image for scene {scene}",
            )
        )
        return commands

    if any(
        phrase in lower
        for phrase in (
            "regenerate video",
            "regen video",
            "re-generate video",
            "generate video",
            "rerender video",
            "re-render video",
        )
    ):
        if scene is None:
            return []
        commands.append(
            CopilotCommand(
                type=CommandType.REGENERATE_VIDEO,
                scene_id=scene,
                summary=f"Regenerate video for scene {scene}",
            )
        )
        return commands

    # --- duration ---
    if "duration" in lower or "seconds" in lower or "runtime" in lower:
        dur_match = (
            _DURATION_RE.search(text)
            or _DURATION_ALT_RE.search(text)
            or _DURATION_OF_SCENE_RE.search(text)
        )
        if dur_match:
            if dur_match.re is _DURATION_OF_SCENE_RE:
                scene = int(dur_match.group(1))
                seconds = float(dur_match.group(2))
            else:
                seconds = float(dur_match.group(1))
            if scene is not None:
                commands.append(
                    CopilotCommand(
                        type=CommandType.CHANGE_DURATION,
                        scene_id=scene,
                        value=seconds,
                        updates={"duration_seconds": seconds},
                        summary=f"Set scene {scene} duration to {seconds}s",
                    )
                )
                return commands

    # --- camera / lighting / emotion (explicit) ---
    camera_val = _quoted_or_after(
        text,
        (
            "camera to",
            "camera:",
            "set camera",
            "change camera to",
            "change camera",
        ),
    )
    if camera_val and scene is not None and "lighting" not in camera_val.casefold():
        # Avoid swallowing "change camera lighting..."
        if not any(k in lower for k in ("lighting to", "emotion to")) or "camera" in lower:
            commands.append(
                CopilotCommand(
                    type=CommandType.CHANGE_CAMERA,
                    scene_id=scene,
                    value=camera_val,
                    updates={"camera": camera_val},
                    summary=f"Set scene {scene} camera to {camera_val}",
                )
            )

    lighting_val = _quoted_or_after(
        text,
        (
            "lighting to",
            "lighting:",
            "set lighting",
            "change lighting to",
            "change lighting",
            "light to",
        ),
    )
    if lighting_val and scene is not None:
        commands.append(
            CopilotCommand(
                type=CommandType.CHANGE_LIGHTING,
                scene_id=scene,
                value=lighting_val,
                updates={"lighting": lighting_val},
                summary=f"Set scene {scene} lighting to {lighting_val}",
            )
        )

    emotion_val = _quoted_or_after(
        text,
        (
            "emotion to",
            "emotion:",
            "set emotion",
            "change emotion to",
            "change emotion",
            "mood to",
        ),
    )
    if emotion_val and scene is not None:
        commands.append(
            CopilotCommand(
                type=CommandType.CHANGE_EMOTION,
                scene_id=scene,
                value=emotion_val,
                updates={"emotion": emotion_val},
                summary=f"Set scene {scene} emotion to {emotion_val}",
            )
        )

    if commands:
        return commands

    # --- character / world / style ---
    if any(k in lower for k in ("character", "costume", "appearance", "wardrobe")):
        name = _quoted_or_after(
            text,
            ("character ", "update character ", "modify character ", "make "),
        )
        notes = _quoted_or_after(
            text,
            ("look ", "appearance ", "notes ", "to ", "with "),
        )
        target = name or "primary"
        # Prefer explicit name tokens after "character"
        name_match = re.search(
            r"character\s+([A-Za-z][A-Za-z0-9 .'-]{1,40})",
            text,
            re.IGNORECASE,
        )
        if name_match:
            target = name_match.group(1).strip(" .,")
        patch: dict[str, Any] = {}
        if notes:
            patch["notes"] = notes
        if "older" in lower:
            patch.setdefault("appearance", {})["age"] = "older"
        if "bicorne" in lower or "hat" in lower:
            patch.setdefault("appearance", {}).setdefault("uniform", {})[
                "hat"
            ] = "bicorne"
        if not patch and notes:
            patch["notes"] = notes
        if patch:
            commands.append(
                CopilotCommand(
                    type=CommandType.MODIFY_CHARACTER,
                    target_name=target,
                    updates=patch,
                    summary=f"Modify character {target}",
                )
            )
            return commands

    if any(k in lower for k in ("world", "location", "era", "season")):
        notes = _quoted_or_after(
            text,
            ("world to", "location to", "era to", "season to", "world ", "location "),
        )
        updates: dict[str, Any] = {}
        if "era to" in lower or lower.startswith("era"):
            updates["era"] = notes or _quoted_or_after(text, ("era to", "era "))
        elif "season" in lower:
            updates["season"] = notes or _quoted_or_after(text, ("season to", "season "))
        elif notes:
            updates["location_notes"] = notes
            updates["location_name"] = notes
        if updates:
            commands.append(
                CopilotCommand(
                    type=CommandType.MODIFY_WORLD,
                    updates={k: v for k, v in updates.items() if v},
                    summary="Modify world / location memory",
                )
            )
            return commands

    if "style" in lower:
        style_val = _quoted_or_after(
            text,
            ("style to", "visual style to", "style:", "style "),
        )
        if style_val:
            commands.append(
                CopilotCommand(
                    type=CommandType.MODIFY_STYLE,
                    updates={"visual_style": style_val},
                    summary=f"Set visual style to {style_val}",
                )
            )
            return commands

    # --- generic edit scene ---
    if scene is not None and any(
        k in lower for k in ("edit scene", "update scene", "change scene", "set scene")
    ):
        updates: dict[str, Any] = {}
        for field, keys in (
            ("title", ("title to", "title:")),
            ("description", ("description to", "description:")),
            ("goal", ("goal to", "goal:")),
            ("image_prompt", ("prompt to", "image prompt to", "prompt:")),
            ("location", ("location to", "location:")),
        ):
            val = _quoted_or_after(text, keys)
            if val:
                updates[field] = val
        if updates:
            commands.append(
                CopilotCommand(
                    type=CommandType.EDIT_SCENE,
                    scene_id=scene,
                    updates=updates,
                    summary=f"Edit scene {scene}: {', '.join(updates)}",
                )
            )
            return commands

    # Shorthand: "make scene 2 darker" / "scene 3 more tense"
    if scene is not None:
        if "darker" in lower or "moonlight" in lower or "night" in lower:
            lighting = "moonlight" if "moonlight" in lower else "low-key darker"
            commands.append(
                CopilotCommand(
                    type=CommandType.CHANGE_LIGHTING,
                    scene_id=scene,
                    value=lighting,
                    updates={"lighting": lighting},
                    summary=f"Set scene {scene} lighting to {lighting}",
                )
            )
            return commands
        if "tense" in lower or "tension" in lower:
            commands.append(
                CopilotCommand(
                    type=CommandType.CHANGE_EMOTION,
                    scene_id=scene,
                    value="Tension",
                    updates={"emotion": "Tension"},
                    summary=f"Set scene {scene} emotion to Tension",
                )
            )
            return commands

    return commands
