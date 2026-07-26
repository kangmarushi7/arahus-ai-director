"""ORM model: :class:`Image`."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, utc_now
from src.database.models._helpers import enum_values

if TYPE_CHECKING:
    from src.database.models.prompt_version import PromptVersion


class ImageStatus(str, enum.Enum):
    """Lifecycle status for a rendered :class:`Image`."""

    PENDING = "pending"
    PROCESSING = "processing"
    OK = "ok"
    GENERATED_NO_URL = "generated_no_url"
    FAILED = "failed"


class Image(Base):
    """A rendered image produced from a :class:`PromptVersion`."""

    __tablename__ = "images"
    __table_args__ = (
        Index("ix_images_prompt_status", "prompt_version_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    status: Mapped[ImageStatus] = mapped_column(
        Enum(
            ImageStatus,
            name="image_status",
            values_callable=enum_values,
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=ImageStatus.PENDING,
        server_default=ImageStatus.PENDING.value,
        index=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    prompt_version: Mapped[PromptVersion] = relationship(back_populates="images")

    def __repr__(self) -> str:
        return (
            f"<Image id={self.id!r} prompt_version_id={self.prompt_version_id!r} "
            f"status={self.status!r} url={self.url!r}>"
        )
