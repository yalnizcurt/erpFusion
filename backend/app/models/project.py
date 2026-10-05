"""
HighStudio — Project Model

A project encapsulates one integration requirement, its ERP schema context,
template references, and all generated artifacts.
"""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, ForeignKeyConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ProjectStatus, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.identity import Client, ERPEnvironment, ERPInstallation


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["erp_installation_id", "client_id"],
            ["erp_installations.id", "erp_installations.client_id"],
            ondelete="SET NULL",
            name="fk_projects_installation_client",
        ),
        ForeignKeyConstraint(
            ["erp_environment_id", "client_id"],
            ["erp_environments.id", "erp_environments.client_id"],
            ondelete="SET NULL",
            name="fk_projects_environment_client",
        ),
    )

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
        String(36),
        ForeignKey("erp_profile_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    integration_pattern_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_pattern_versions.id"), index=True
    )
    # Ownership is nullable during the reviewed legacy reconciliation period.
    # New request APIs must populate these fields from authenticated context.
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    erp_installation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    erp_environment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by_subject_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("identity_subjects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requirement_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    schema_context_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    project_type: Mapped[str] = mapped_column(String(16), default="CUSTOM", nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    workflow_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)

    # ── Status ────────────────────────────────────────────────
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status", native_enum=False),
        default=ProjectStatus.ACTIVE,
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────
    artifacts: Mapped[list["Artifact"]] = relationship(  # noqa: F821
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    client: Mapped["Client | None"] = relationship(  # noqa: F821
        foreign_keys=[client_id],
    )
    installation: Mapped["ERPInstallation | None"] = relationship(  # noqa: F821
        foreign_keys=[erp_installation_id],
    )
    environment: Mapped["ERPEnvironment | None"] = relationship(  # noqa: F821
        foreign_keys=[erp_environment_id],
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name!r}, status={self.status})>"
