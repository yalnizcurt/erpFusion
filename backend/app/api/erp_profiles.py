"""ERP profile lifecycle and version-scoped prompt, package, and knowledge registries."""

import hashlib
import io
import json
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import require_erp_admin
from app.config import get_settings
from app.database import get_db
from app.models import (
    AdminAuditEvent,
    ERPAssetVersion,
    ERPProfile,
    ERPProfileVersion,
    FeedbackGuidance,
    GenerationRun,
    PromptVersion,
    Project,
)

router = APIRouter(prefix="/api/erp-profiles", tags=["ERP Profiles"])
VALID_PROFILE_STATES = {"DRAFT", "REVIEW", "PUBLISHED", "RETIRED"}
VALID_PROMPT_SCOPES = {"GLOBAL", "ERP", "STAGE"}
VALID_ASSET_KINDS = {"PACKAGE", "KNOWLEDGE"}
VALID_ASSET_STATES = {"DRAFT", "REVIEW", "PUBLISHED", "RETIRED"}


@router.get("")
async def list_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ERPProfile, ERPProfileVersion)
        .join(ERPProfileVersion, ERPProfileVersion.profile_id == ERPProfile.id)
        .where(ERPProfileVersion.status == "PUBLISHED", ERPProfile.active.is_(True))
        .order_by(ERPProfile.display_name, ERPProfileVersion.version.desc())
    )
    seen: set[str] = set()
    response = []
    for profile, version in result.all():
        if profile.id not in seen:
            response.append(_public_profile_json(profile, version))
            seen.add(profile.id)
    return response


@router.get("/admin")
async def list_profiles_admin(
    _actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(ERPProfile).order_by(ERPProfile.display_name))
    profiles = result.scalars().all()
    response = []
    for profile in profiles:
        versions = await db.execute(
            select(ERPProfileVersion).where(ERPProfileVersion.profile_id == profile.id)
            .order_by(ERPProfileVersion.version.desc())
        )
        response.append({**_profile_json(profile), "versions": [_version_json(v) for v in versions.scalars()]})
    return response


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: dict, actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)
):
    required = ("name", "vendor", "version")
    if any(not isinstance(body.get(k), str) or not body[k].strip() for k in required):
        raise HTTPException(400, "name, vendor, and version are required")
    key = re.sub(r"[^a-z0-9]+", "-", body["name"].strip().lower()).strip("-")[:80]
    if not key:
        raise HTTPException(400, "ERP name must contain letters or numbers")
    exists = await db.execute(select(ERPProfile.id).where(ERPProfile.key == key))
    if exists.scalar_one_or_none():
        key = f"{key}-{uuid4().hex[:6]}"

    types = body.get("supported_artifact_types") or []
    configuration = body.get("configuration") or {}
    if not isinstance(types, list) or not all(isinstance(x, str) for x in types):
        raise HTTPException(400, "supported_artifact_types must be a list of strings")
    if not isinstance(configuration, dict):
        raise HTTPException(400, "configuration must be an object")
    profile = ERPProfile(
        key=key, name=body["name"].strip(), display_name=(body.get("display_name") or body["name"]).strip(),
        vendor=body["vendor"].strip(), product_version=body["version"].strip(),
        description=body.get("description"), active=True, status="DRAFT", created_by=actor, updated_by=actor,
        configuration=configuration,
    )
    db.add(profile)
    await db.flush()
    profile_version = ERPProfileVersion(
        profile_id=profile.id, version=1, status="DRAFT", supported_artifact_types=types,
        configuration=configuration, created_by=actor, updated_by=actor,
    )
    db.add(profile_version)
    await _audit(db, actor, "PROFILE_CREATED", "ERPProfile", profile.id, {"profile_version": 1})
    await db.flush()
    return _profile_json(profile, profile_version)


@router.post("/{profile_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_profile_version(
    profile_id: str, actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)
):
    profile = await _get_profile(profile_id, db)
    result = await db.execute(
        select(ERPProfileVersion).where(ERPProfileVersion.profile_id == profile_id)
        .order_by(ERPProfileVersion.version.desc()).limit(1)
    )
    latest = result.scalar_one_or_none()
    if latest is None:
        raise HTTPException(409, "Profile has no version")
    if latest.status in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "Finish or retire the current draft version before creating another")
    published_result = await db.execute(select(ERPProfileVersion).where(
        ERPProfileVersion.profile_id == profile_id, ERPProfileVersion.status == "PUBLISHED"
    ).order_by(ERPProfileVersion.version.desc()).limit(1))
    previous = published_result.scalar_one_or_none()
    if previous is None:
        raise HTTPException(409, "Publish a profile version before creating a new version")
    version = ERPProfileVersion(
        profile_id=profile.id, version=latest.version + 1, status="DRAFT",
        supported_artifact_types=list(previous.supported_artifact_types),
        configuration=dict(previous.configuration), created_by=actor, updated_by=actor,
    )
    db.add(version)
    await db.flush()
    prompts_result = await db.execute(select(PromptVersion).where(PromptVersion.profile_version_id == previous.id))
    for prompt in prompts_result.scalars():
        db.add(PromptVersion(
            scope=prompt.scope, profile_version_id=version.id, name=prompt.name, stage=prompt.stage,
            content=prompt.content, version=prompt.version, status=prompt.status,
            variables=list(prompt.variables or []), created_by=actor, updated_by=actor,
        ))
    assets_result = await db.execute(select(ERPAssetVersion).where(
        ERPAssetVersion.profile_version_id == previous.id, ERPAssetVersion.status == "PUBLISHED"))
    latest_assets = {}
    for asset in assets_result.scalars():
        if asset.asset_id not in latest_assets or asset.version > latest_assets[asset.asset_id].version:
            latest_assets[asset.asset_id] = asset
    for asset in latest_assets.values():
        db.add(ERPAssetVersion(
            asset_id=asset.asset_id, profile_version_id=version.id, asset_kind=asset.asset_kind,
            name=asset.name, description=asset.description, package_type=asset.package_type,
            version=asset.version, status="PUBLISHED", storage_path=asset.storage_path,
            file_name=asset.file_name, mime_type=asset.mime_type, checksum=asset.checksum,
            text_content=asset.text_content, metadata_json=dict(asset.metadata_json or {}), created_by=actor,
        ))
    await _audit(db, actor, "PROFILE_VERSION_CREATED", "ERPProfile", profile.id, {"version": version.version})
    await db.flush()
    return _version_json(version)


@router.put("/{profile_id}/versions/{version_number}")
async def update_profile_version(
    profile_id: str, version_number: int, body: dict,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    version = await _get_profile_version(profile_id, version_number, db)
    if version.status not in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "Published or retired profile versions are immutable; create a new version.")
    if "supported_artifact_types" in body:
        if not isinstance(body["supported_artifact_types"], list):
            raise HTTPException(400, "supported_artifact_types must be a list")
        version.supported_artifact_types = body["supported_artifact_types"]
    if "configuration" in body:
        if not isinstance(body["configuration"], dict):
            raise HTTPException(400, "configuration must be an object")
        version.configuration = body["configuration"]
    if "status" in body:
        if body["status"] not in {"DRAFT", "REVIEW"}:
            raise HTTPException(400, "A draft can only move between DRAFT and REVIEW here")
        version.status = body["status"]
    version.updated_by = actor
    await _audit(db, actor, "PROFILE_VERSION_UPDATED", "ERPProfileVersion", version.id, {"version": version.version})
    await db.flush()
    return _version_json(version)


@router.post("/{profile_id}/versions/{version_number}/publish")
async def publish_profile_version(
    profile_id: str, version_number: int,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(profile_id, db)
    version = await _get_profile_version(profile_id, version_number, db)
    if version.status not in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "Only draft or review versions can be published")
    if not version.supported_artifact_types:
        raise HTTPException(409, "Configure at least one supported artifact type before publishing")
    stages = version.configuration.get("workflow", {}).get("stages", [])
    if not stages:
        raise HTTPException(409, "Configure workflow stages and dependencies before publishing")
    prompt_stages = {s.get("prompt_stage", s.get("type")) for s in stages if isinstance(s, dict)}
    prompt_result = await db.execute(
        select(PromptVersion.stage).where(
            PromptVersion.profile_version_id == version.id,
            PromptVersion.scope.in_(["ERP", "STAGE"]), PromptVersion.status == "PUBLISHED",
        )
    )
    configured = set(prompt_result.scalars().all())
    missing = sorted(stage for stage in prompt_stages if stage not in configured and stage != "REVIEW_FEEDBACK")
    if missing:
        raise HTTPException(409, f"Publish prompts for these workflow stages first: {', '.join(missing)}")
    version.status = "PUBLISHED"
    version.updated_by = actor
    version.published_at = datetime.now(timezone.utc)
    profile.status = "PUBLISHED"
    profile.active = True
    profile.updated_by = actor
    await _audit(db, actor, "PROFILE_VERSION_PUBLISHED", "ERPProfileVersion", version.id, {"version": version.version})
    await db.flush()
    return _profile_json(profile, version)


@router.post("/{profile_id}/versions/{version_number}/retire")
async def retire_profile_version(
    profile_id: str, version_number: int,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(profile_id, db)
    version = await _get_profile_version(profile_id, version_number, db)
    if version.status != "PUBLISHED":
        raise HTTPException(409, "Only a published profile version can be retired")
    version.status = "RETIRED"
    version.updated_by = actor
    remaining = await db.execute(select(ERPProfileVersion.id).where(
        ERPProfileVersion.profile_id == profile_id, ERPProfileVersion.status == "PUBLISHED"))
    has_published = remaining.first() is not None
    profile.status = "PUBLISHED" if has_published else "RETIRED"
    profile.active = has_published
    await _audit(db, actor, "PROFILE_VERSION_RETIRED", "ERPProfileVersion", version.id, {"version": version.version})
    await db.flush()
    return _version_json(version)


@router.get("/{profile_id}/prompts")
async def list_prompts(profile_id: str, version: int, _actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)):
    profile_version = await _get_profile_version(profile_id, version, db)
    result = await db.execute(select(PromptVersion).where(PromptVersion.profile_version_id == profile_version.id)
                              .order_by(PromptVersion.scope, PromptVersion.stage, PromptVersion.version.desc()))
    return [_prompt_json(x) for x in result.scalars()]


@router.post("/{profile_id}/versions/{version_number}/prompts", status_code=201)
async def create_prompt(
    profile_id: str, version_number: int, body: dict,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    profile_version = await _get_profile_version(profile_id, version_number, db)
    if profile_version.status not in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "Prompts may only be added to draft profile versions")
    scope = str(body.get("scope", "STAGE")).upper()
    name, stage, content = body.get("name"), body.get("stage"), body.get("content")
    if scope not in {"ERP", "STAGE"} or not all(isinstance(x, str) and x.strip() for x in (name, stage, content)):
        raise HTTPException(400, "scope (ERP/STAGE), name, stage, and content are required")
    result = await db.execute(select(func.max(PromptVersion.version)).where(
        PromptVersion.profile_version_id == profile_version.id, PromptVersion.scope == scope,
        PromptVersion.name == name.strip(), PromptVersion.stage == stage.strip().upper()))
    declared_variables = body.get("variables")
    if declared_variables is None:
        declared_variables = _prompt_variables(content)
    if not isinstance(declared_variables, list) or not all(isinstance(value, str) for value in declared_variables):
        raise HTTPException(400, "variables must be a list of strings")
    item = PromptVersion(
        scope=scope, profile_version_id=profile_version.id, name=name.strip(), stage=stage.strip().upper(),
        content=content, version=(result.scalar_one() or 0) + 1, status="DRAFT",
        variables=declared_variables, created_by=actor, updated_by=actor,
    )
    db.add(item)
    await db.flush()
    await _audit(db, actor, "PROMPT_CREATED", "PromptVersion", item.id, {"version": item.version})
    return _prompt_json(item)


@router.post("/{profile_id}/prompts/{prompt_id}/publish")
async def publish_prompt(
    profile_id: str, prompt_id: str,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    item = await db.get(PromptVersion, prompt_id)
    if not item or not item.profile_version_id:
        raise HTTPException(404, "Prompt not found")
    profile_version = await db.get(ERPProfileVersion, item.profile_version_id)
    if profile_version.profile_id != profile_id:
        raise HTTPException(404, "Prompt not found")
    if profile_version.status not in {"DRAFT", "REVIEW"} or item.status != "DRAFT":
        raise HTTPException(409, "Only draft prompts on a draft ERP profile can be published")
    item.status = "PUBLISHED"
    item.updated_by = actor
    await _audit(db, actor, "PROMPT_PUBLISHED", "PromptVersion", item.id, {"version": item.version})
    await db.flush()
    return _prompt_json(item)


@router.post("/{profile_id}/prompts/{prompt_id}/retire")
async def retire_prompt(
    profile_id: str, prompt_id: str,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    item = await db.get(PromptVersion, prompt_id)
    if item is None or not item.profile_version_id:
        raise HTTPException(404, "Prompt not found")
    profile_version = await db.get(ERPProfileVersion, item.profile_version_id)
    if profile_version.profile_id != profile_id:
        raise HTTPException(404, "Prompt not found")
    if profile_version.status not in {"DRAFT", "REVIEW"} or item.status != "PUBLISHED":
        raise HTTPException(409, "Retire prompt copies only on a draft profile version")
    item.status = "RETIRED"
    item.updated_by = actor
    await _audit(db, actor, "PROMPT_RETIRED", "PromptVersion", item.id, {"version": item.version})
    await db.flush()
    return _prompt_json(item)


@router.get("/{profile_id}/versions/{version_number}/assets")
async def list_assets(profile_id: str, version_number: int, _actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)):
    profile_version = await _get_profile_version(profile_id, version_number, db)
    result = await db.execute(select(ERPAssetVersion).where(ERPAssetVersion.profile_version_id == profile_version.id)
                              .order_by(ERPAssetVersion.asset_kind, ERPAssetVersion.name, ERPAssetVersion.version.desc()))
    return [_asset_json(x) for x in result.scalars()]


@router.post("/{profile_id}/versions/{version_number}/assets", status_code=201)
async def create_text_asset(
    profile_id: str, version_number: int, body: dict,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    profile_version = await _get_profile_version(profile_id, version_number, db)
    if profile_version.status not in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "Assets may only be added to draft profile versions")
    kind = str(body.get("asset_kind", "KNOWLEDGE")).upper()
    name, content = body.get("name"), body.get("text_content")
    if kind not in VALID_ASSET_KINDS or not isinstance(name, str) or not name.strip():
        raise HTTPException(400, "Provide a valid asset_kind and name")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(400, "text_content is required for text assets")
    asset_id, asset_version = await _next_asset_version(db, profile_version.id, name.strip(), kind)
    item = ERPAssetVersion(
        asset_id=asset_id, profile_version_id=profile_version.id, asset_kind=kind, name=name.strip(),
        description=body.get("description"), package_type=body.get("package_type"), version=asset_version,
        status="DRAFT", text_content=content, metadata_json=body.get("metadata") or {}, created_by=actor,
        checksum=hashlib.sha256(content.encode()).hexdigest(),
    )
    db.add(item)
    await db.flush()
    await _audit(db, actor, f"{kind}_ASSET_CREATED", "ERPAssetVersion", item.id, {"version": item.version})
    return _asset_json(item)


@router.post("/{profile_id}/versions/{version_number}/assets/upload", status_code=201)
async def upload_asset(
    profile_id: str, version_number: int, asset_kind: str, name: str, package_type: str | None = None,
    description: str | None = None, files: list[UploadFile] = File(...),
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    profile_version = await _get_profile_version(profile_id, version_number, db)
    if profile_version.status not in {"DRAFT", "REVIEW"}:
        raise HTTPException(409, "Assets may only be uploaded to draft profile versions")
    kind = asset_kind.upper()
    if kind not in VALID_ASSET_KINDS or not name.strip() or not files:
        raise HTTPException(400, "Provide asset_kind, name, and at least one file")
    base_path = Path(get_settings().artifact_storage_path).resolve() / "erp-assets" / profile_version.id
    asset_id, asset_version = await _next_asset_version(db, profile_version.id, name.strip(), kind)
    asset_directory = base_path / asset_id / str(asset_version)
    asset_directory.mkdir(parents=True, exist_ok=True)
    uploaded = []
    total_size = 0
    textual_parts = []
    for upload in files:
        safe_name = Path(upload.filename or "upload.bin").name
        data = await upload.read(25 * 1024 * 1024 + 1)
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, f"{safe_name} exceeds the 25 MB per-file limit")
        if not data:
            continue
        total_size += len(data)
        digest = hashlib.sha256(data).hexdigest()
        destination = asset_directory / safe_name
        destination.write_bytes(data)
        uploaded.append({"file_name": safe_name, "mime_type": upload.content_type,
                         "storage_path": str(destination), "checksum": digest, "size": len(data)})
        textual_parts.extend(_extract_text_parts(safe_name, upload.content_type, data))
    if not uploaded:
        raise HTTPException(400, "Uploaded files were empty")
    item = ERPAssetVersion(
        asset_id=asset_id, profile_version_id=profile_version.id, asset_kind=kind, name=name.strip(),
        description=description, package_type=package_type, version=asset_version, status="DRAFT",
        storage_path=str(asset_directory),
        file_name=uploaded[0]["file_name"] if len(uploaded) == 1 else None,
        mime_type=uploaded[0]["mime_type"] if len(uploaded) == 1 else "application/x-multiple-files",
        checksum=hashlib.sha256("".join(x["checksum"] for x in uploaded).encode()).hexdigest(),
        text_content="\n\n".join(textual_parts) or None,
        metadata_json={"size": total_size, "files": uploaded}, created_by=actor,
    )
    db.add(item)
    await db.flush()
    await _audit(db, actor, f"{kind}_ASSET_UPLOADED", "ERPAssetVersion", item.id,
                 {"name": name, "file_count": len(uploaded), "version": asset_version})
    return [_asset_json(item)]


@router.post("/{profile_id}/assets/{asset_id}/versions/{asset_version}/publish")
async def publish_asset(
    profile_id: str, asset_id: str, asset_version: int,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    item = await _get_asset(profile_id, asset_id, asset_version, db)
    profile_version = await db.get(ERPProfileVersion, item.profile_version_id)
    if profile_version.status not in {"DRAFT", "REVIEW"} or item.status != "DRAFT":
        raise HTTPException(409, "Only assets on draft profile versions can be published")
    item.status = "PUBLISHED"
    await _audit(db, actor, "ASSET_PUBLISHED", "ERPAssetVersion", item.id, {"version": item.version})
    await db.flush()
    return _asset_json(item)


@router.post("/{profile_id}/assets/{asset_id}/versions/{asset_version}/retire")
async def retire_asset(
    profile_id: str, asset_id: str, asset_version: int,
    actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db),
):
    item = await _get_asset(profile_id, asset_id, asset_version, db)
    profile_version = await db.get(ERPProfileVersion, item.profile_version_id)
    if profile_version.status not in {"DRAFT", "REVIEW"} or item.status != "PUBLISHED":
        raise HTTPException(409, "Retire asset copies only on a draft profile version")
    item.status = "RETIRED"
    await _audit(db, actor, "ASSET_RETIRED", "ERPAssetVersion", item.id, {"version": item.version})
    await db.flush()
    return _asset_json(item)


@router.get("/{profile_id}/versions/{version_number}/feedback")
async def list_feedback(profile_id: str, version_number: int, _actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)):
    await _get_profile_version(profile_id, version_number, db)
    result = await db.execute(select(FeedbackGuidance).where(
        FeedbackGuidance.profile_id == profile_id,
        FeedbackGuidance.scope == "ERP", FeedbackGuidance.status == "APPROVED"))
    return [_feedback_json(x) for x in result.scalars()]


@router.get("/{profile_id}/versions/{version_number}/audit")
async def list_profile_audit(profile_id: str, version_number: int, _actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)):
    await _get_profile_version(profile_id, version_number, db)
    versions = await db.execute(select(ERPProfileVersion.id).where(ERPProfileVersion.profile_id == profile_id))
    version_ids = list(versions.scalars())
    prompt_ids = await db.execute(select(PromptVersion.id).where(PromptVersion.profile_version_id.in_(version_ids)))
    asset_ids = await db.execute(select(ERPAssetVersion.id).where(ERPAssetVersion.profile_version_id.in_(version_ids)))
    feedback_ids = await db.execute(select(FeedbackGuidance.id).where(FeedbackGuidance.profile_id == profile_id))
    entity_ids = [profile_id, *version_ids, *prompt_ids.scalars(), *asset_ids.scalars(), *feedback_ids.scalars()]
    result = await db.execute(select(AdminAuditEvent).where(
        AdminAuditEvent.entity_id.in_(entity_ids)
    ).order_by(AdminAuditEvent.created_at.desc()).limit(200))
    return [{"id": e.id, "actor": e.actor, "action": e.action, "entity_type": e.entity_type,
             "entity_id": e.entity_id, "details": e.details, "created_at": e.created_at}
            for e in result.scalars()]


@router.get("/{profile_id}/usage")
async def profile_usage(profile_id: str, _actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)):
    profile = await _get_profile(profile_id, db)
    projects = await db.execute(select(func.count()).select_from(Project).where(Project.erp_profile_id == profile.id))
    runs = await db.execute(select(func.count()).select_from(GenerationRun).join(
        ERPProfileVersion, GenerationRun.profile_version_id == ERPProfileVersion.id
    ).where(ERPProfileVersion.profile_id == profile.id))
    return {"profile_id": profile.id, "integration_requests": projects.scalar_one(),
            "generation_runs": runs.scalar_one()}


@router.get("/global-prompts")
async def list_global_prompts(_actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PromptVersion).where(PromptVersion.scope == "GLOBAL")
                              .order_by(PromptVersion.stage, PromptVersion.version.desc()))
    return [_prompt_json(p) for p in result.scalars()]


@router.get("/feedback")
async def list_project_feedback(_actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)):
    """Expose project-scoped reviewer guidance for explicit admin promotion decisions."""
    result = await db.execute(
        select(FeedbackGuidance, Project.name, Project.erp_profile_id)
        .join(Project, Project.id == FeedbackGuidance.project_id)
        .where(FeedbackGuidance.scope == "PROJECT")
        .order_by(FeedbackGuidance.created_at.desc()).limit(500)
    )
    return [{**_feedback_json(item), "project_id": item.project_id, "project_name": project_name,
             "profile_id": profile_id} for item, project_name, profile_id in result.all()]


@router.post("/global-prompts", status_code=201)
async def create_global_prompt(
    body: dict, actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)
):
    name, stage, content = body.get("name"), body.get("stage"), body.get("content")
    if not all(isinstance(x, str) and x.strip() for x in (name, stage, content)):
        raise HTTPException(400, "name, stage, and content are required")
    result = await db.execute(select(func.max(PromptVersion.version)).where(
        PromptVersion.scope == "GLOBAL", PromptVersion.profile_version_id.is_(None),
        PromptVersion.name == name.strip(), PromptVersion.stage == stage.strip().upper()))
    declared_variables = body.get("variables")
    if declared_variables is None:
        declared_variables = _prompt_variables(content)
    if not isinstance(declared_variables, list) or not all(isinstance(value, str) for value in declared_variables):
        raise HTTPException(400, "variables must be a list of strings")
    item = PromptVersion(scope="GLOBAL", profile_version_id=None, name=name.strip(),
        stage=stage.strip().upper(), content=content, version=(result.scalar_one() or 0) + 1,
        status="DRAFT", variables=declared_variables, created_by=actor, updated_by=actor)
    db.add(item)
    await db.flush()
    await _audit(db, actor, "GLOBAL_PROMPT_CREATED", "PromptVersion", item.id, {"version": item.version})
    return _prompt_json(item)


@router.post("/global-prompts/{prompt_id}/publish")
async def publish_global_prompt(
    prompt_id: str, actor: str = Depends(require_erp_admin), db: AsyncSession = Depends(get_db)
):
    item = await db.get(PromptVersion, prompt_id)
    if item is None or item.scope != "GLOBAL" or item.status != "DRAFT":
        raise HTTPException(404, "Draft global prompt not found")
    item.status = "PUBLISHED"
    item.updated_by = actor
    await _audit(db, actor, "GLOBAL_PROMPT_PUBLISHED", "PromptVersion", item.id, {"version": item.version})
    await db.flush()
    return _prompt_json(item)


async def _get_profile(profile_id: str, db: AsyncSession) -> ERPProfile:
    item = await db.get(ERPProfile, profile_id)
    if item is None:
        raise HTTPException(404, "ERP profile not found")
    return item


async def _get_profile_version(profile_id: str, version_number: int, db: AsyncSession) -> ERPProfileVersion:
    result = await db.execute(select(ERPProfileVersion).where(
        ERPProfileVersion.profile_id == profile_id, ERPProfileVersion.version == version_number))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "ERP profile version not found")
    return item


async def _next_asset_version(db: AsyncSession, profile_version_id: str, name: str, kind: str):
    result = await db.execute(select(ERPAssetVersion).where(
        ERPAssetVersion.profile_version_id == profile_version_id,
        ERPAssetVersion.name == name, ERPAssetVersion.asset_kind == kind)
        .order_by(ERPAssetVersion.version.desc()).limit(1))
    previous = result.scalar_one_or_none()
    return (previous.asset_id, previous.version + 1) if previous else (str(uuid4()), 1)


async def _get_asset(profile_id: str, asset_id: str, version: int, db: AsyncSession):
    result = await db.execute(select(ERPAssetVersion).join(
        ERPProfileVersion, ERPAssetVersion.profile_version_id == ERPProfileVersion.id
    ).where(ERPProfileVersion.profile_id == profile_id, ERPAssetVersion.asset_id == asset_id,
            ERPAssetVersion.version == version))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Asset version not found")
    return item


async def _audit(db, actor: str, action: str, entity_type: str, entity_id: str, details: dict):
    db.add(AdminAuditEvent(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, details=details))


def _profile_json(profile: ERPProfile, version: ERPProfileVersion | None = None):
    return {"id": profile.id, "key": profile.key, "name": profile.name, "display_name": profile.display_name,
            "vendor": profile.vendor, "version_label": profile.product_version, "description": profile.description,
            "status": version.status if version else profile.status, "active": profile.active,
            "profile_version_id": version.id if version else None,
            "profile_version": version.version if version else None,
            "supported_artifact_types": version.supported_artifact_types if version else [],
            "configuration": version.configuration if version else profile.configuration}


def _public_profile_json(profile: ERPProfile, version: ERPProfileVersion):
    """Return only selector metadata; prompts, validation, and asset config remain admin-only."""
    return {"id": profile.id, "key": profile.key, "name": profile.name,
            "display_name": profile.display_name, "vendor": profile.vendor,
            "version_label": profile.product_version, "description": profile.description,
            "status": version.status, "profile_version_id": version.id,
            "profile_version": version.version,
            "supported_artifact_types": version.supported_artifact_types}


def _version_json(v: ERPProfileVersion):
    return {"id": v.id, "profile_id": v.profile_id, "version": v.version, "status": v.status,
            "supported_artifact_types": v.supported_artifact_types, "configuration": v.configuration,
            "published_at": v.published_at, "created_at": v.created_at}


def _prompt_json(p: PromptVersion):
    return {"id": p.id, "scope": p.scope, "name": p.name, "stage": p.stage, "content": p.content,
            "version": p.version, "status": p.status, "variables": p.variables}


def _asset_json(a: ERPAssetVersion):
    return {"id": a.id, "asset_id": a.asset_id, "asset_kind": a.asset_kind, "name": a.name,
            "description": a.description, "package_type": a.package_type, "version": a.version,
            "status": a.status, "file_name": a.file_name, "mime_type": a.mime_type,
            "checksum": a.checksum, "files": [x.get("file_name") for x in (a.metadata_json or {}).get("files", [])],
            "metadata": a.metadata_json}


def _feedback_json(x: FeedbackGuidance):
    return {"id": x.id, "scope": x.scope, "stage": x.stage, "content": x.content,
            "status": x.status, "version": x.version}


def _looks_text(mime_type: str | None, filename: str) -> bool:
    return bool((mime_type or "").startswith("text/") or Path(filename).suffix.lower() in
                {".sql", ".plsql", ".pks", ".pkb", ".py", ".js", ".json", ".xml", ".md", ".txt", ".abap", ".yaml", ".yml"})


def _extract_text_parts(filename: str, mime_type: str | None, data: bytes) -> list[str]:
    """Index bounded text sources in files and archives without extracting archive paths."""
    if _looks_text(mime_type, filename):
        return [f"### {filename}\n{data[:512_000].decode('utf-8', errors='ignore')}"]
    lowered = filename.lower()
    entries: list[tuple[str, bytes]] = []
    try:
        if lowered.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist()[:100]:
                    if info.is_dir() or info.file_size > 512_000 or not _looks_text(None, info.filename):
                        continue
                    with archive.open(info) as stream:
                        entries.append((info.filename, stream.read(512_001)[:512_000]))
        elif lowered.endswith((".tar", ".tar.gz", ".tgz")):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                for info in archive.getmembers()[:100]:
                    if not info.isfile() or info.size > 512_000 or not _looks_text(None, info.name):
                        continue
                    stream = archive.extractfile(info)
                    if stream:
                        entries.append((info.name, stream.read(512_001)[:512_000]))
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        return []

    result = []
    remaining = 2_000_000
    for path, content in entries:
        if remaining <= 0:
            break
        bounded = content[:remaining]
        result.append(f"### {filename}!/{Path(path).name}\n{bounded.decode('utf-8', errors='ignore')}")
        remaining -= len(bounded)
    return result


def _prompt_variables(content: str) -> list[str]:
    return sorted(set(re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", content)))
