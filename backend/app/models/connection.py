"""Client/environment connection metadata; secret material never enters these rows."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ERPConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "erp_connections"
    __table_args__ = (
        UniqueConstraint("environment_id", name="uq_connection_environment"),
        UniqueConstraint("id", "client_id", name="uq_connection_id_client"),
        ForeignKeyConstraint(
            ["environment_id", "client_id"],
            ["erp_environments.id", "erp_environments.client_id"],
            name="fk_connection_environment_client",
            ondelete="CASCADE",
        ),
    )

    client_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    environment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    vendor_configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    expected_tenant: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_hosts: Mapped[list] = mapped_column(JSON, nullable=False)
    report_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    permitted_operations: Mapped[list] = mapped_column(JSON, nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    secret_ref: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    secret_version: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ConnectionVerification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "connection_verifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "client_id"],
            ["erp_connections.id", "erp_connections.client_id"],
            name="fk_verification_connection_client",
            ondelete="CASCADE",
        ),
    )

    client_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    connection_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False)
    secret_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False)
    diagnostic_code: Mapped[str] = mapped_column(String(80), nullable=False)
