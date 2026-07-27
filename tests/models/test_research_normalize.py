"""Unit tests for ResearchResult JSON normalization."""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from src.models.research import ResearchResult
from src.models.research_normalize import normalize_research_payload


class TestGeminiStyleObjects:
    def test_list_items_as_named_objects(self) -> None:
        payload = {
            "topic": "The Fall of Constantinople",
            "time_period": 1453,
            "location": "Constantinople",
            "weapons": [
                {
                    "name": "Orban's Cannon",
                    "description": "Giant bombard used by Ottomans.",
                },
                {"name": "Crossbows", "details": "Used by Genoese mercenaries."},
            ],
            "clothing": [
                {
                    "group": "Byzantine Soldiers",
                    "details": "Lamellar armor; elites wore plate.",
                }
            ],
            "important_events": [
                {
                    "event": "Final Assault",
                    "date": "29 May 1453",
                    "details": "Breach near St. Romanus Gate.",
                }
            ],
            "visual_details": [
                {
                    "element": "Ottoman Camp",
                    "details": "Tents outside the walls.",
                }
            ],
            "historical_notes": [
                {"note": "End of the Byzantine Empire.", "year": 1453}
            ],
            "extra_gemini_meta": {"ignored": True},
        }
        result = ResearchResult.model_validate(payload)
        assert result.topic == "The Fall of Constantinople"
        assert result.time_period == "1453"
        assert result.weapons[0] == "Orban's Cannon"
        assert result.weapons[1] == "Crossbows"
        assert "Byzantine Soldiers" in result.clothing[0]
        assert "Final Assault" in result.important_events[0]
        assert "Ottoman Camp" in result.visual_details[0]
        assert "End of the Byzantine Empire." in result.historical_notes[0]


class TestClaudeStyle:
    def test_plain_string_arrays(self) -> None:
        payload = {
            "topic": "Bitcoin ETF",
            "time_period": "2024",
            "location": "United States",
            "key_people": ["Gary Gensler", "BlackRock"],
            "key_locations": ["SEC headquarters", "NYSE"],
            "architecture": [],
            "weapons": [],
            "clothing": [],
            "important_events": ["Spot Bitcoin ETF approval"],
            "visual_details": ["Trading floor screens", "BTC price tickers"],
            "historical_notes": ["First US spot Bitcoin ETFs launched in 2024"],
        }
        result = ResearchResult.model_validate(payload)
        assert result.key_people == ["Gary Gensler", "BlackRock"]
        assert result.important_events == ["Spot Bitcoin ETF approval"]
        assert result.architecture == []


class TestDeepSeekStyle:
    def test_nested_title_value_objects_and_numbers(self) -> None:
        payload = {
            "topic": "Life on Mars in 2150",
            "time_period": 2150,
            "location": {"name": "Olympus Mons colony"},
            "key_people": [
                {"title": "Colony Governor"},
                {"value": "Chief Engineer"},
                {"label": "Hab Designer"},
            ],
            "key_locations": [{"text": "Valles Marineris"}],
            "architecture": [{"description": "Pressurized geodesic domes"}],
            "weapons": None,
            "clothing": "Pressure suit with dust filters",
            "important_events": 2150,
            "visual_details": ["Red dust storms", 3.7, True],
            "historical_notes": {"note": "First permanent settlement era"},
        }
        result = ResearchResult.model_validate(payload)
        assert result.time_period == "2150"
        assert result.location == "Olympus Mons colony"
        assert result.key_people == [
            "Colony Governor",
            "Chief Engineer",
            "Hab Designer",
        ]
        assert result.key_locations == ["Valles Marineris"]
        assert result.architecture == ["Pressurized geodesic domes"]
        assert result.weapons == []
        assert result.clothing == ["Pressure suit with dust filters"]
        assert result.important_events == ["2150"]
        assert result.visual_details == ["Red dust storms", "3.7", "true"]
        assert result.historical_notes == ["First permanent settlement era"]


class TestMixedArrays:
    def test_mixed_strings_objects_nulls_numbers(self) -> None:
        payload = {
            "topic": "Mixed",
            "key_people": [
                "Alice",
                {"name": "Bob", "role": "scout"},
                None,
                "",
                42,
                {"title": "Carol"},
            ],
        }
        result = ResearchResult.model_validate(payload)
        assert result.key_people == ["Alice", "Bob", "42", "Carol"]
        assert result.location == ""
        assert result.historical_notes == []


class TestMissingOptionalFields:
    def test_topic_only_payload(self) -> None:
        result = ResearchResult.model_validate({"topic": "Minimal Topic"})
        assert result.topic == "Minimal Topic"
        assert result.time_period == ""
        assert result.location == ""
        assert result.key_people == []
        assert result.visual_details == []

    def test_unknown_fields_ignored(self) -> None:
        result = ResearchResult.model_validate(
            {
                "topic": "X",
                "confidence": 0.9,
                "sources": ["a", "b"],
                "model_notes": {"foo": 1},
            }
        )
        assert result.topic == "X"
        assert not hasattr(result, "confidence")


class TestRequiredTopic:
    def test_missing_topic_raises(self) -> None:
        with pytest.raises((ValueError, ValidationError), match="topic"):
            ResearchResult.model_validate({"location": "Somewhere"})

    def test_empty_topic_raises(self) -> None:
        with pytest.raises((ValueError, ValidationError), match="topic"):
            ResearchResult.model_validate({"topic": "   "})

    def test_non_object_raises(self) -> None:
        with pytest.raises((ValueError, ValidationError)):
            ResearchResult.model_validate(["not", "an", "object"])


class TestNormalizeFunctionDirect:
    def test_priority_order_prefers_name_over_description(self) -> None:
        out = normalize_research_payload(
            {
                "topic": "T",
                "weapons": [
                    {"description": "secondary", "name": "primary"},
                ],
            }
        )
        assert out["weapons"] == ["primary"]

    def test_debug_logs_coercions(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="src.models.research_normalize"):
            normalize_research_payload(
                {
                    "topic": "T",
                    "time_period": 1453,
                    "weapons": [{"name": "Cannon"}],
                    "unknown_field": 1,
                }
            )
        messages = " ".join(r.message for r in caplog.records)
        assert "research_coerce" in messages
        assert "number_to_str" in messages or "drop_unknown" in messages


class TestQwenStyle:
    def test_single_object_for_list_and_whitespace_topic(self) -> None:
        result = ResearchResult.model_validate(
            {
                "topic": "  Mars  Colony  ",
                "key_locations": {"name": "Jezero Crater"},
                "architecture": "Hab modules",
            }
        )
        assert result.topic == "Mars Colony"
        assert result.key_locations == ["Jezero Crater"]
        assert result.architecture == ["Hab modules"]
