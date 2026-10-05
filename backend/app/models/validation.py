"""
HighStudio — ValidationResult Model

Stores the results of automated validation checks performed on an
artifact version before it is presented for human review.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin, ValidationCategory, ValidationStatus

if TYPE_CHECKING:
    from app.models.version import ArtifactVersion


class ValidationResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "validation_results"

    # ── Foreign Keys ──────────────────────────────────────────
    artifact_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("artifact_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Validation Info ───────────────────────────────────────
    category: Mapped[ValidationCategory] = mapped_column(
        Enum(ValidationCategory, name="validation_category", native_enum=False),
        nullable=False,
    )

    status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus, name="validation_status", native_enum=False),
        nullable=False,
    )

    checks: Mapped[list[dict]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Array of individual check results: [{name, status, message, details}]",
    )

    # ── Timestamp ─────────────────────────────────────────────
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────
    artifact_version: Mapped["ArtifactVersion"] = relationship(  # noqa: F821
        back_populates="validation_results",
    )

    def __repr__(self) -> str:
        return (
            f"<ValidationResult(id={self.id}, category={self.category}, "
            f"status={self.status})>"
        )
