"""Identity, client ownership, and ERP environment models.

These models deliberately store the stable identity claims needed for
authorization without making the application an identity provider.  An OIDC
adapter can resolve an authenticated subject to ``IdentitySubject`` and the
authorization layer can then evaluate the explicit memberships below.

Ownership is represented as data.  No model or migration attempts to infer a
client from a project name or from an ERP profile.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IdentitySubject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A stable subject from an explicitly configured identity issuer."""

    __tablename__ = "identity_subjects"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_identity_subject_issuer_subject"),
    )

    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client_memberships: Mapped[list["ClientMembership"]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="ClientMembership.subject_id",
    )
    platform_roles: Mapped[list["PlatformRoleAssignment"]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="PlatformRoleAssignment.subject_id",
    )


class Client(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer boundary for requests, artifacts, environments, and audit."""

    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("id", "client_key", name="uq_clients_id_client_key"),)

    client_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list["ClientMembership"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", lazy="selectin"
    )
    installations: Mapped[list["ERPInstallation"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", lazy="selectin"
    )
    environments: Mapped[list["ERPEnvironment"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
        overlaps="environments,client,installation",
    )


class ClientMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A client-scoped role assignment for an authenticated subject."""

    __tablename__ = "client_memberships"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "subject_id", "role", name="uq_client_membership_subject_role"
        ),
    )

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("identity_subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )

    client: Mapped[Client] = relationship(back_populates="memberships", foreign_keys=[client_id])
    subject: Mapped[IdentitySubject] = relationship(
        back_populates="client_memberships", foreign_keys=[subject_id]
    )


class PlatformRoleAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A platform-level role, separate from any client's roles."""

    __tablename__ = "platform_role_assignments"
    __table_args__ = (UniqueConstraint("subject_id", "role", name="uq_platform_role_subject_role"),)

    subject_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("identity_subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )

    subject: Mapped[IdentitySubject] = relationship(
        back_populates="platform_roles", foreign_keys=[subject_id]
    )


class ERPInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One client's installed/configured instance of an ERP profile."""

    __tablename__ = "erp_installations"
    __table_args__ = (
        UniqueConstraint("client_id", "installation_key", name="uq_erp_installation_client_key"),
        UniqueConstraint("id", "client_id", name="uq_erp_installation_id_client"),
    )

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    erp_profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("erp_profiles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    installation_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    edition: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_tenant_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[Client] = relationship(back_populates="installations")
    environments: Mapped[list["ERPEnvironment"]] = relationship(
        back_populates="installation",
        cascade="all, delete-orphan",
        lazy="selectin",
        overlaps="environments,client,installation",
    )


class ERPEnvironment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named execution/discovery environment belonging to an installation."""

    __tablename__ = "erp_environments"
    __table_args__ = (
        UniqueConstraint(
            "installation_id", "environment_key", name="uq_erp_environment_installation_key"
        ),
        UniqueConstraint("id", "client_id", name="uq_erp_environment_id_client"),
        ForeignKeyConstraint(
            ["installation_id", "client_id"],
            ["erp_installations.id", "erp_installations.client_id"],
            ondelete="CASCADE",
            name="fk_erp_environment_installation_client",
        ),
    )

    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    environment_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    environment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="SANDBOX")
    custody: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED")
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="ASSISTED")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_subject_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_subjects.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[Client] = relationship(
        back_populates="environments",
        foreign_keys=[client_id],
        overlaps="environments,installation",
    )
    installation: Mapped[ERPInstallation] = relationship(
        back_populates="environments", overlaps="environments,client"
    )
