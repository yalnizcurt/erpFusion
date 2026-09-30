"""Versioned ERP expertise profiles and stage prompt registry."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ERPProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "erp_profiles"

    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    product_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    prompts: Mapped[list["ERPStagePrompt"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )
    versions: Mapped[list["ERPProfileVersion"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="ERPProfileVersion.version"
    )


class ERPProfileVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "erp_profile_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version", name="uq_erp_profile_version"),)

    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("erp_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)
    supported_artifact_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile: Mapped[ERPProfile] = relationship(back_populates="versions")


class ERPStagePrompt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "erp_stage_prompts"
    __table_args__ = (
        UniqueConstraint("profile_id", "stage", "version", name="uq_profile_stage_version"),
    )

    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("erp_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("erp_profile_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), default="Stage prompt", nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="ERP", nullable=False)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PUBLISHED", nullable=False)
    variables: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    profile: Mapped[ERPProfile] = relationship(back_populates="prompts")
