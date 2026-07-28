"""ORM models for pipeline request audit logs."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now
from src.database.models._helpers import enum_values


class PipelineRunStatus(str, enum.Enum):
    """Lifecycle status for a :class:`PipelineRun` audit record."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineLogKind(str, enum.Enum):
    """Kind of a :class:`PipelineLogEntry`."""

    LLM = "llm"
    IMAGE = "image"
    VIDEO = "video"
    STAGE = "stage"


class PipelineRun(Base):
    """One pipeline request (admin-visible run id)."""

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_status_started_at", "status", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    topic: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[PipelineRunStatus] = mapped_column(
        Enum(
            PipelineRunStatus,
            name="pipeline_run_status",
            values_callable=enum_values,
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=PipelineRunStatus.RUNNING,
        server_default=PipelineRunStatus.RUNNING.value,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    entries: Mapped[list[PipelineLogEntry]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PipelineLogEntry.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<PipelineRun id={self.id!r} topic={self.topic!r} "
            f"status={self.status!r}>"
        )


class PipelineLogEntry(Base):
    """One tagged step (LLM / image / video / stage) inside a run."""

    __tablename__ = "pipeline_log_entries"
    __table_args__ = (
        Index("ix_pipeline_log_entries_run_tag", "run_id", "tag"),
        Index("ix_pipeline_log_entries_run_kind", "run_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[PipelineLogKind] = mapped_column(
        Enum(
            PipelineLogKind,
            name="pipeline_log_kind",
            values_callable=enum_values,
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    request: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped[PipelineRun] = relationship(back_populates="entries")

    def __repr__(self) -> str:
        return (
            f"<PipelineLogEntry id={self.id!r} tag={self.tag!r} "
            f"kind={self.kind!r}>"
        )
