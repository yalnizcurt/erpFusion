"""
erpFusion — AuditEntry Model

Records every action taken on an artifact version — creation, validation,
review decisions, invalidations, and regenerations. Provides full traceability
for the engineering process.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditAction, Base, UUIDPrimaryKeyMixin


class AuditEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_entries"

    # ── Foreign Keys ──────────────────────────────────────────
    artifact_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("artifact_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Action ────────────────────────────────────────────────
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action"),
        nullable=False,
    )

    # ── Actor ─────────────────────────────────────────────────
    actor: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="'system' | 'ai' | 'human:<user_id>'",
    )

    # ── Details ───────────────────────────────────────────────
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        comment="Additional structured metadata about the action",
    )

    # ── Timestamp ─────────────────────────────────────────────
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # ── Relationships ─────────────────────────────────────────
    artifact_version: Mapped["ArtifactVersion"] = relationship(  # noqa: F821
        back_populates="audit_entries",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditEntry(id={self.id}, action={self.action}, "
            f"actor={self.actor!r}, ts={self.timestamp})>"
        )
