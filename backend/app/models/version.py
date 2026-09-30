"""
erpFusion — ArtifactVersion Model

Each version is an immutable snapshot of an artifact's content at a point
in time. Approved versions are never modified in place — changes produce
a new version.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin, VersionState


class ArtifactVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "artifact_versions"

    # ── Foreign Keys ──────────────────────────────────────────
    artifact_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Versioning ────────────────────────────────────────────
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── State ─────────────────────────────────────────────────
    state: Mapped[VersionState] = mapped_column(
        Enum(VersionState, name="version_state"),
        default=VersionState.DRAFT,
        nullable=False,
    )

    # ── Content ───────────────────────────────────────────────
    content: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Structured artifact content (Pydantic model serialized to JSON)",
    )

    file_path: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Path to rendered file (.docx, .sql, .pks, .pkb)",
    )

    # ── Lineage ───────────────────────────────────────────────
    parent_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artifact_versions.id", ondelete="SET NULL"),
        nullable=True,
        comment="Previous version this was derived from",
    )

    input_context_snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Frozen snapshot of the inputs used for generation",
    )

    # ── Generation Metadata ───────────────────────────────────
    ai_model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generation_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Human Review Fields ───────────────────────────────────
    reviewer: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Human reviewer identifier",
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_comments: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human reviewer comments",
    )

    # ── Relationships ─────────────────────────────────────────
    artifact: Mapped["Artifact"] = relationship(back_populates="versions")  # noqa: F821

    audit_entries: Mapped[list["AuditEntry"]] = relationship(  # noqa: F821
        back_populates="artifact_version",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AuditEntry.timestamp",
    )

    validation_results: Mapped[list["ValidationResult"]] = relationship(  # noqa: F821
        back_populates="artifact_version",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<ArtifactVersion(id={self.id}, artifact={self.artifact_id}, "
            f"v{self.version_number}, state={self.state})>"
        )
