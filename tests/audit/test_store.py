"""Unit tests for pipeline audit file store."""

from __future__ import annotations

from pathlib import Path

from src.audit import store as audit_store


def test_audit_run_records_tagged_llm_and_images(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(audit_store, "_DEFAULT_DIR", tmp_path / "runs")

    with audit_store.audit_run("Test topic", run_id="11111111-1111-1111-1111-111111111111") as run:
        audit_store.record_llm_exchange(
            tag="research",
            request="[user]\nresearch please",
            response='{"ok": true}',
            model="test-model",
            provider="openrouter",
            latency_ms=12.5,
            input_tokens=10,
            output_tokens=20,
            estimated_cost=0.001,
        )
        audit_store.record_image_result(
            scene_id=1,
            title="Scene one",
            prompt="a castle",
            url="https://example.com/a.png",
            status="ok",
        )
        audit_store.record_video_result(status="not_generated")
        run.finish(status="completed", summary={"scene_count": 1})
        audit_store.save_run(run)

    rows = audit_store.list_runs(limit=10)
    assert len(rows) == 1
    assert rows[0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert rows[0]["llm_steps"] == 1
    assert rows[0]["image_steps"] == 1

    full = audit_store.load_run("11111111-1111-1111-1111-111111111111")
    assert full is not None
    tags = [step["tag"] for step in full["steps"]]
    assert tags == ["research", "images", "video"]
    assert full["steps"][0]["request"].startswith("[user]")
    assert full["steps"][1]["response"] == "https://example.com/a.png"


def test_messages_to_prompt_text() -> None:
    text = audit_store.messages_to_prompt_text(
        [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
        ]
    )
    assert "[system]\nBe helpful" in text
    assert "[user]\nHello" in text
