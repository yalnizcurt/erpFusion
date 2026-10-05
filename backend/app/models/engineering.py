"""Client-owned document revisions and immutable package/test evidence."""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ProjectInputRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_input_revisions"
    __table_args__ = (UniqueConstraint("project_id", "revision", name="uq_project_input_revision"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_by_subject_id: Mapped[str | None] = mapped_column(ForeignKey("identity_subjects.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RequirementDocument(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "requirement_documents"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(1024))
    extraction_status: Mapped[str] = mapped_column(String(24))
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    extraction_error: Mapped[str | None] = mapped_column(String(80))
    scan_status: Mapped[str] = mapped_column(String(24), default="NOT_CONFIGURED")
    requirement_version: Mapped[int] = mapped_column(Integer)
    created_by_subject_id: Mapped[str | None] = mapped_column(ForeignKey("identity_subjects.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PackageCandidate(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "package_candidates"
    __table_args__ = (
        UniqueConstraint("project_id", "checksum", name="uq_project_package_checksum"),
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id"), index=True)
    checksum: Mapped[str] = mapped_column(String(64))
    integration_pattern_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_pattern_versions.id")
    )
    manifest: Mapped[dict] = mapped_column(JSON)
    storage_path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SandboxEvidence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sandbox_evidence"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("package_candidates.id"))
    environment_id: Mapped[str] = mapped_column(ForeignKey("erp_environments.id"))
    candidate_checksum: Mapped[str] = mapped_column(String(64))
    connection_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    method: Mapped[str] = mapped_column(String(40))
    execution_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("execution_attempts.id"))
    observations: Mapped[dict] = mapped_column(JSON)
    tester_subject_id: Mapped[str | None] = mapped_column(ForeignKey("identity_subjects.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PackageRelease(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "package_releases"
    __table_args__ = (
        UniqueConstraint("candidate_id", "evidence_id", name="uq_package_release_evidence"),
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("package_candidates.id"))
    evidence_id: Mapped[str] = mapped_column(ForeignKey("sandbox_evidence.id"))
    checksum: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict] = mapped_column(JSON)
    storage_path: Mapped[str] = mapped_column(String(1024))
    approved_by_subject_id: Mapped[str | None] = mapped_column(ForeignKey("identity_subjects.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
