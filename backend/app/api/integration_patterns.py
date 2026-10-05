"""Governed pattern versions and exact approved baseline associations."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select

from app.api.admin_auth import require_erp_admin, require_erp_publisher, require_erp_reader
from app.api.connections import _RedactedValidationRoute
from app.database import get_db
from app.models import (
    ERPAssetVersion,
    ERPProfile,
    ERPProfileVersion,
    IntegrationPattern,
    IntegrationPatternVersion,
    PatternBaseline,
)
from app.security.identity import Identity, get_current_identity
from app.services.codegen.strategies import get_strategy
from app.services.execution_contracts import adapter_supports_pattern
from app.services.integration_patterns import validate_configuration, validate_pattern_version
from app.services.ownership_audit import record_ownership_event

router = APIRouter(
    prefix="/api/integration-patterns",
    tags=["Integration patterns"],
    route_class=_RedactedValidationRoute,
)


class PatternCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    erp_profile_id: str
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(default="HighRadius", min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)


class PatternVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_version_id: str
    runtime_type: Literal[
        "ERP_NATIVE", "EXTERNAL_RUNTIME", "API_INTEGRATION", "FILE_BASED", "ASSISTED"
    ]
    direction: Literal["OUTBOUND", "INBOUND", "BIDIRECTIONAL"] = "OUTBOUND"
    deliverable_type: str = Field(min_length=1, max_length=80)
    qualification_strategy: Literal[
        "NATIVE_ARTIFACT", "REMOTE_API", "FILE_EXCHANGE", "EXTERNAL_RUNTIME", "ASSISTED"
    ]
    delivery_method: str = Field(default="CUSTOMER_CONTROLLED", min_length=1, max_length=80)
    configuration: dict = Field(default_factory=dict)
    baseline_asset_version_ids: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("configuration")
    @classmethod
    def public_contract(cls, value):
        return validate_configuration(value)


async def get_pattern(db, identifier):
    pattern = await db.scalar(
        select(IntegrationPattern).where(IntegrationPattern.id == identifier).with_for_update()
    )
    if not pattern:
        raise HTTPException(404, "Integration pattern not found")
    return pattern


async def set_baselines(db, pattern, version, identifiers):
    if len(set(identifiers)) != len(identifiers):
        raise HTTPException(422, "duplicate_baseline_versions")
    for identifier in identifiers:
        asset = await db.get(ERPAssetVersion, identifier)
        profile = await db.get(ERPProfileVersion, asset.profile_version_id) if asset else None
        if (
            not asset
            or asset.status != "PUBLISHED"
            or asset.asset_kind != "PACKAGE"
            or not profile
            or profile.profile_id != pattern.erp_profile_id
        ):
            raise HTTPException(409, "baseline_must_be_published_standard_package_for_product")
    await db.execute(
        delete(PatternBaseline).where(PatternBaseline.pattern_version_id == version.id)
    )
    db.add_all(
        [
            PatternBaseline(pattern_version_id=version.id, asset_version_id=identifier)
            for identifier in identifiers
        ]
    )
    await db.flush()


async def version_response(db, version):
    identifiers = list(
        await db.scalars(
            select(PatternBaseline.asset_version_id).where(
                PatternBaseline.pattern_version_id == version.id
            )
        )
    )
    adapters = version.configuration.get("adapter_bindings", {})
    adapter_status = {
        mode: "IMPLEMENTED"
        if adapter_supports_pattern(adapter, mode, version.runtime_type, version.deliverable_type)
        else "NOT_IMPLEMENTED"
        for mode, adapter in adapters.items()
    }
    rules = version.configuration.get("generation_rules", {})
    profile = await db.get(ERPProfileVersion, version.profile_version_id)
    stages = {
        s["type"]
        for s in (profile.configuration if profile else {}).get("workflow", {}).get("stages", [])
    }
    status = "CONFIGURATION_ONLY"
    try:
        strategy = get_strategy(rules.get("strategy", ""))
    except ValueError:
        strategy = None
    if (
        strategy is not None
        and rules.get("strategy_version") == "1"
        and rules.get("stages")
        and set(rules["stages"]) <= stages
        and (not rules.get("baseline_required", True) or strategy.supports_baseline)
    ):
        status = (
            "GENERATION_SUPPORTED"
            if identifiers or not rules.get("baseline_required", True)
            else "BASELINE_REQUIRED"
        )
    if (
        status == "GENERATION_SUPPORTED"
        and version.status == "PUBLISHED"
        and adapter_status.get("SIMULATED") == "IMPLEMENTED"
    ):
        status = "SIMULATOR_SUPPORTED"
    return {
        **{column.name: getattr(version, column.name) for column in version.__table__.columns},
        "baseline_asset_version_ids": identifiers,
        "implementation_status": status,
        "adapter_support": adapter_status,
        "qualification": "ENVIRONMENT_SPECIFIC_REQUIRED",
    }


@router.get("")
async def list_patterns(
    erp_profile_id: str | None = None,
    include_drafts: bool = False,
    db=Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    if include_drafts and not (identity.can_configure_erp or identity.can_publish_erp):
        raise HTTPException(403, "ERP administration role required")
    query = select(IntegrationPattern)
    if erp_profile_id:
        query = query.where(IntegrationPattern.erp_profile_id == erp_profile_id)
    result = []
    for pattern in await db.scalars(query.order_by(IntegrationPattern.name)):
        versions_query = select(IntegrationPatternVersion).where(
            IntegrationPatternVersion.pattern_id == pattern.id
        )
        if not include_drafts:
            versions_query = versions_query.where(IntegrationPatternVersion.status == "PUBLISHED")
        versions = [
            await version_response(db, v)
            for v in await db.scalars(
                versions_query.order_by(IntegrationPatternVersion.version.desc())
            )
        ]
        result.append(
            {
                **{
                    column.name: getattr(pattern, column.name)
                    for column in pattern.__table__.columns
                },
                "versions": versions,
            }
        )
    return result


@router.get("/baseline-assets")
async def baseline_assets(
    erp_profile_id: str, db=Depends(get_db), actor: str = Depends(require_erp_reader)
):
    assets = await db.scalars(
        select(ERPAssetVersion)
        .join(ERPProfileVersion, ERPProfileVersion.id == ERPAssetVersion.profile_version_id)
        .where(
            ERPProfileVersion.profile_id == erp_profile_id,
            ERPAssetVersion.status == "PUBLISHED",
            ERPAssetVersion.asset_kind == "PACKAGE",
        )
        .order_by(ERPAssetVersion.name, ERPAssetVersion.version.desc())
    )
    return [
        {
            "id": a.id,
            "name": a.name,
            "version": a.version,
            "status": a.status,
            "asset_kind": a.asset_kind,
            "profile_version_id": a.profile_version_id,
            "checksum": a.checksum,
        }
        for a in assets
    ]


@router.post("", status_code=201)
async def create_pattern(
    body: PatternCreate,
    db=Depends(get_db),
    actor: str = Depends(require_erp_admin),
    identity: Identity = Depends(get_current_identity),
):
    if not await db.get(ERPProfile, body.erp_profile_id):
        raise HTTPException(404, "ERP product not found")
    exists = await db.scalar(
        select(IntegrationPattern.id).where(
            IntegrationPattern.erp_profile_id == body.erp_profile_id,
            IntegrationPattern.key == body.key,
        )
    )
    if exists:
        raise HTTPException(409, "pattern_key_already_exists")
    pattern = IntegrationPattern(**body.model_dump(), created_by=actor)
    db.add(pattern)
    await db.flush()
    await record_ownership_event(
        db, identity, "INTEGRATION_PATTERN_CREATED", "IntegrationPattern", pattern.id
    )
    return {"id": pattern.id}


@router.post("/{pattern_id}/versions", status_code=201)
async def create_version(
    pattern_id: str,
    body: PatternVersionInput,
    db=Depends(get_db),
    actor: str = Depends(require_erp_admin),
    identity: Identity = Depends(get_current_identity),
):
    pattern = await get_pattern(db, pattern_id)
    profile = await db.get(ERPProfileVersion, body.profile_version_id)
    if not profile or profile.profile_id != pattern.erp_profile_id:
        raise HTTPException(409, "pattern_product_intelligence_mismatch")
    number = (
        await db.scalar(
            select(func.max(IntegrationPatternVersion.version)).where(
                IntegrationPatternVersion.pattern_id == pattern.id
            )
        )
        or 0
    ) + 1
    version = IntegrationPatternVersion(
        pattern_id=pattern.id,
        version=number,
        created_by=actor,
        **body.model_dump(exclude={"baseline_asset_version_ids"}),
    )
    db.add(version)
    await db.flush()
    await set_baselines(db, pattern, version, body.baseline_asset_version_ids)
    await record_ownership_event(
        db, identity, "PATTERN_VERSION_CREATED", "IntegrationPatternVersion", version.id
    )
    return await version_response(db, version)


async def get_version(db, pattern_id, version_id):
    pattern = await get_pattern(db, pattern_id)
    version = await db.get(IntegrationPatternVersion, version_id)
    if not version or version.pattern_id != pattern.id:
        raise HTTPException(404, "Pattern version not found")
    return pattern, version


@router.put("/{pattern_id}/versions/{version_id}")
async def edit_version(
    pattern_id: str,
    version_id: str,
    body: PatternVersionInput,
    db=Depends(get_db),
    actor: str = Depends(require_erp_admin),
    identity: Identity = Depends(get_current_identity),
):
    pattern, version = await get_version(db, pattern_id, version_id)
    if version.status not in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "published_pattern_versions_are_immutable_create_a_new_version")
    profile = await db.get(ERPProfileVersion, body.profile_version_id)
    if not profile or profile.profile_id != pattern.erp_profile_id:
        raise HTTPException(409, "pattern_product_intelligence_mismatch")
    for key, value in body.model_dump(exclude={"baseline_asset_version_ids"}).items():
        setattr(version, key, value)
    await set_baselines(db, pattern, version, body.baseline_asset_version_ids)
    await record_ownership_event(
        db, identity, "PATTERN_VERSION_UPDATED", "IntegrationPatternVersion", version.id
    )
    return await version_response(db, version)


@router.post("/{pattern_id}/versions/{version_id}/publish")
async def publish(
    pattern_id: str,
    version_id: str,
    db=Depends(get_db),
    actor: str = Depends(require_erp_publisher),
    identity: Identity = Depends(get_current_identity),
):
    pattern, version = await get_version(db, pattern_id, version_id)
    if version.status not in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "draft_or_review_pattern_version_required")
    await validate_pattern_version(db, pattern, version)
    version.status, version.published_at = "PUBLISHED", datetime.now(UTC)
    await record_ownership_event(
        db, identity, "PATTERN_VERSION_PUBLISHED", "IntegrationPatternVersion", version.id
    )
    return await version_response(db, version)


@router.post("/{pattern_id}/versions/{version_id}/retire")
async def retire(
    pattern_id: str,
    version_id: str,
    db=Depends(get_db),
    actor: str = Depends(require_erp_publisher),
    identity: Identity = Depends(get_current_identity),
):
    pattern, version = await get_version(db, pattern_id, version_id)
    if version.status != "PUBLISHED":
        raise HTTPException(409, "published_pattern_version_required")
    version.status = "RETIRED"
    await record_ownership_event(
        db, identity, "PATTERN_VERSION_RETIRED", "IntegrationPatternVersion", version.id
    )
    return await version_response(db, version)
