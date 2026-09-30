"""
erpFusion — Project Model

A project encapsulates one integration requirement, its ERP schema context,
template references, and all generated artifacts.
"""

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ProjectStatus, TimestampMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    # ── Identity ──────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Inputs ────────────────────────────────────────────────
    business_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    erp_schema_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # ── Template references (file paths for now, Google Docs URLs later)
    fdd_template_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tdd_template_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    erp_profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("erp_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    erp_profile_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("erp_profile_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    requirement_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    schema_context_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # ── Status ────────────────────────────────────────────────
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        default=ProjectStatus.ACTIVE,
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────
    artifacts: Mapped[list["Artifact"]] = relationship(  # noqa: F821
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name!r}, status={self.status})>"
