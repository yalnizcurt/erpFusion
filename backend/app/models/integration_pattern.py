"""HighRadius integration patterns reuse ERP intelligence and approved asset versions."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationPattern(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_patterns"
    __table_args__ = (UniqueConstraint("erp_profile_id", "key", name="uq_product_pattern"),)
    erp_profile_id: Mapped[str] = mapped_column(ForeignKey("erp_profiles.id"), index=True)
    provider: Mapped[str] = mapped_column(String(80), default="HighRadius")
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000), default="")
    created_by: Mapped[str] = mapped_column(String(255))


class IntegrationPatternVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_pattern_versions"
    __table_args__ = (UniqueConstraint("pattern_id", "version", name="uq_pattern_version"),)
    pattern_id: Mapped[str] = mapped_column(ForeignKey("integration_patterns.id"), index=True)
    # The existing profile version remains authoritative for workflow/prompts,
    # knowledge and generation/validation defaults. Do not duplicate those here.
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("erp_profile_versions.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    runtime_type: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(16))
    deliverable_type: Mapped[str] = mapped_column(String(80))
    qualification_strategy: Mapped[str] = mapped_column(String(32))
    delivery_method: Mapped[str] = mapped_column(String(80))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PatternBaseline(Base):
    __tablename__ = "pattern_baselines"
    pattern_version_id: Mapped[str] = mapped_column(
        ForeignKey("integration_pattern_versions.id"), primary_key=True
    )
    asset_version_id: Mapped[str] = mapped_column(
        ForeignKey("erp_asset_versions.id"), primary_key=True
    )
