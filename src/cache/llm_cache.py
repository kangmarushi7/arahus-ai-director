"""Thread-safe SQLite cache for LLM JSON responses.

Entries are keyed by a SHA-256 digest of ``(model, temperature, prompt)`` so
identical requests never hit the provider twice.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _build_cache_key(model: str, temperature: float, prompt: str) -> str:
    """Hash model, temperature, and prompt into a stable SHA-256 key."""
    payload = json.dumps(
        {
            "model": model,
            "temperature": temperature,
            "prompt": prompt,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheStatistics:
    """Snapshot of cache hit/miss counters and entry count."""

    hits: int
    misses: int
    size: int


class LLMCache:
    """SQLite-backed cache for JSON LLM responses.

    The cache is process-local and thread-safe. Callers pass the model name,
    temperature, and full prompt; responses are stored and retrieved as JSON
    values (``dict`` / ``list`` / scalars).
    """

    def __init__(self, db_path: str | Path = ".cache/llm_cache.sqlite3") -> None:
        """Open (or create) the SQLite database at ``db_path``.

        Args:
            db_path: Filesystem path for the SQLite file. Parent directories are
                created automatically.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create the cache table when the database is empty."""
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @property
    def hits(self) -> int:
        """Number of successful cache lookups since construction or :meth:`clear`."""
        with self._lock:
            return self._hits

    @property
    def misses(self) -> int:
        """Number of failed cache lookups since construction or :meth:`clear`."""
        with self._lock:
            return self._misses

    @property
    def size(self) -> int:
        """Number of entries currently stored in the cache."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()
            return int(row[0]) if row else 0

    def statistics(self) -> CacheStatistics:
        """Return a snapshot of hits, misses, and entry count."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()
            size = int(row[0]) if row else 0
            return CacheStatistics(hits=self._hits, misses=self._misses, size=size)

    def get(self, model: str, temperature: float, prompt: str) -> Any | None:
        """Return the cached JSON value, or ``None`` on a miss.

        Args:
            model: Model identifier used for the request.
            temperature: Sampling temperature used for the request.
            prompt: Full prompt text.

        Returns:
            The deserialized JSON payload, or ``None`` if absent.
        """
        cache_key = _build_cache_key(model, temperature, prompt)
        with self._lock:
            row = self._conn.execute(
                "SELECT response_json FROM llm_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                self._misses += 1
                return None

            self._hits += 1
            return json.loads(row[0])

    def set(
        self,
        model: str,
        temperature: float,
        prompt: str,
        value: Any,
    ) -> None:
        """Store ``value`` as JSON under the request key.

        Args:
            model: Model identifier used for the request.
            temperature: Sampling temperature used for the request.
            prompt: Full prompt text.
            value: JSON-serializable response payload.
        """
        cache_key = _build_cache_key(model, temperature, prompt)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        response_json = json.dumps(value, ensure_ascii=False)
        now = _utc_now_iso()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO llm_cache (
                    cache_key,
                    model,
                    temperature,
                    prompt_hash,
                    response_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    model = excluded.model,
                    temperature = excluded.temperature,
                    prompt_hash = excluded.prompt_hash,
                    response_json = excluded.response_json,
                    updated_at = excluded.updated_at
                """,
                (
                    cache_key,
                    model,
                    float(temperature),
                    prompt_hash,
                    response_json,
                    now,
                    now,
                ),
            )

    def clear(self) -> None:
        """Delete every cache entry and reset hit/miss counters."""
        with self._lock:
            self._conn.execute("DELETE FROM llm_cache")
            self._hits = 0
            self._misses = 0

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> LLMCache:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
