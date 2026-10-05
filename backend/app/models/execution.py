"""Durable, client-owned execution receipts; never store secret material here."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class CapabilityQualification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "capability_qualifications"
    __table_args__ = (
        UniqueConstraint("id", "client_id", name="uq_qualification_client"),
        ForeignKeyConstraint(
            ["environment_id", "client_id"], ["erp_environments.id", "erp_environments.client_id"]
        ),
    )
    client_id: Mapped[str] = mapped_column(String(36), index=True)
    environment_id: Mapped[str] = mapped_column(String(36), index=True)
    adapter: Mapped[str] = mapped_column(String(64))
    adapter_version: Mapped[str] = mapped_column(String(32))
    binding: Mapped[dict] = mapped_column(JSON)
    capabilities: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    approved_by_subject_id: Mapped[str] = mapped_column(ForeignKey("identity_subjects.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ExecutionAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_execution_idempotency"),
        UniqueConstraint("id", "client_id", name="uq_execution_client"),
        ForeignKeyConstraint(
            ["environment_id", "client_id"], ["erp_environments.id", "erp_environments.client_id"]
        ),
        ForeignKeyConstraint(
            ["qualification_id", "client_id"],
            ["capability_qualifications.id", "capability_qualifications.client_id"],
        ),
    )
    client_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("package_candidates.id"))
    candidate_checksum: Mapped[str] = mapped_column(String(64))
    integration_pattern_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("integration_pattern_versions.id")
    )
    environment_id: Mapped[str] = mapped_column(String(36), index=True)
    qualification_id: Mapped[str] = mapped_column(String(36))
    connection_id: Mapped[str | None] = mapped_column(ForeignKey("erp_connections.id"))
    adapter: Mapped[str] = mapped_column(String(64))
    adapter_version: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="AWAITING_APPROVAL", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    requested_by_subject_id: Mapped[str] = mapped_column(ForeignKey("identity_subjects.id"))
    approved_by_subject_id: Mapped[str | None] = mapped_column(ForeignKey("identity_subjects.id"))
    approval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    binding: Mapped[dict] = mapped_column(JSON)
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    failure: Mapped[dict] = mapped_column(JSON, default=dict)
    assurance: Mapped[list] = mapped_column(JSON, default=list)
    verdict: Mapped[str] = mapped_column(String(24), default="NOT_RUN")
    external_execution_id: Mapped[str | None] = mapped_column(String(255))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SimulatedArtifact(UUIDPrimaryKeyMixin, Base):
    """Simulator read-back is durable and independent of expected test results."""

    __tablename__ = "simulated_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "client_id"], ["execution_attempts.id", "execution_attempts.client_id"]
        ),
        UniqueConstraint("attempt_id", name="uq_simulated_attempt"),
    )
    client_id: Mapped[str] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str] = mapped_column(String(36))
    environment_id: Mapped[str] = mapped_column(String(36))
    checksum: Mapped[str] = mapped_column(String(64))
    adapter_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    history: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
