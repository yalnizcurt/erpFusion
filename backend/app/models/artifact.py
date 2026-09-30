"""
erpFusion — Artifact Model

An artifact represents one engineering deliverable within a project
(e.g., Context Analysis, FDD, TDD, SQL, PKS, PKB).

Each artifact tracks its current gate status and owns multiple versions.
"""

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GateStatus, TimestampMixin, UUIDPrimaryKeyMixin


class Artifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "artifacts"

    # ── Foreign Keys ──────────────────────────────────────────
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Identity ──────────────────────────────────────────────
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)

    # ── Versioning ────────────────────────────────────────────
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Workflow Gate ─────────────────────────────────────────
    gate_status: Mapped[GateStatus] = mapped_column(
        Enum(GateStatus, name="gate_status"),
        default=GateStatus.LOCKED,
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────
    project: Mapped["Project"] = relationship(back_populates="artifacts")  # noqa: F821

    versions: Mapped[list["ArtifactVersion"]] = relationship(  # noqa: F821
        back_populates="artifact",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ArtifactVersion.version_number",
    )

    def __repr__(self) -> str:
        return (
            f"<Artifact(id={self.id}, type={self.artifact_type}, "
            f"v{self.current_version}, gate={self.gate_status})>"
        )
