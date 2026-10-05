"""Resolve exact pattern/baseline versions without duplicating ERP intelligence."""

import json

from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    ERPAssetVersion,
    ERPInstallation,
    ERPProfileVersion,
    IntegrationPattern,
    IntegrationPatternVersion,
    PatternBaseline,
)
from app.services.packages import json_bytes, sha256

RUNTIME_TYPES = {"ERP_NATIVE", "EXTERNAL_RUNTIME", "API_INTEGRATION", "FILE_BASED", "ASSISTED"}
QUALIFICATION_STRATEGIES = {
    "NATIVE_ARTIFACT",
    "REMOTE_API",
    "FILE_EXCHANGE",
    "EXTERNAL_RUNTIME",
    "ASSISTED",
}


async def resolve_pattern(
    db,
    version_id,
    *,
    profile_id=None,
    profile_version_id=None,
    installation=None,
    allow_retired=False,
):
    version = await db.get(IntegrationPatternVersion, version_id)
    pattern = await db.get(IntegrationPattern, version.pattern_id) if version else None
    if (
        not version
        or not pattern
        or version.status not in ({"PUBLISHED", "RETIRED"} if allow_retired else {"PUBLISHED"})
    ):
        raise HTTPException(409, "published_integration_pattern_version_required")
    if (profile_id and pattern.erp_profile_id != profile_id) or (
        profile_version_id and version.profile_version_id != profile_version_id
    ):
        raise HTTPException(409, "pattern_product_or_intelligence_version_mismatch")
    try:
        validate_configuration(version.configuration)
    except ValueError:
        raise HTTPException(409, "invalid_persisted_pattern_configuration") from None
    compatibility = version.configuration.get("compatibility", {})
    if installation:
        for field in ("edition", "product_version"):
            allowed = compatibility.get(field + "s", [])
            if allowed and getattr(installation, field) not in allowed:
                raise HTTPException(409, "pattern_product_edition_version_not_supported")
    return pattern, version


async def baselines(db, version):
    assets = list(
        await db.scalars(
            select(ERPAssetVersion)
            .join(PatternBaseline, PatternBaseline.asset_version_id == ERPAssetVersion.id)
            .where(PatternBaseline.pattern_version_id == version.id)
            .order_by(ERPAssetVersion.id)
        )
    )
    if (
        version.configuration.get("generation_rules", {}).get("baseline_required", True)
        and not assets
    ):
        raise HTTPException(409, "approved_pattern_baseline_required")
    refs, snapshots = [], []
    for asset in assets:
        if (
            asset.status not in {"PUBLISHED", "RETIRED"}
            or asset.asset_kind != "PACKAGE"
            or not asset.text_content
        ):
            raise HTTPException(409, "published_readable_baseline_version_required")
        profile = await db.get(ERPProfileVersion, asset.profile_version_id)
        owner = await db.get(ERPProfileVersion, version.profile_version_id)
        if not profile or not owner or profile.profile_id != owner.profile_id:
            raise HTTPException(409, "baseline_product_mismatch")
        reference = {
            "id": asset.id,
            "asset_id": asset.asset_id,
            "version": asset.version,
            "checksum": asset.checksum,
            "content_sha256": sha256(asset.text_content.encode()),
        }
        refs.append(reference)
        snapshots.append({**reference, "name": asset.name, "content": asset.text_content})
    if sum(len(s["content"].encode()) for s in snapshots) > 262144:
        raise HTTPException(409, "baseline_context_limit_exceeded")
    return refs, snapshots


async def pattern_context(db, project):
    if not project.integration_pattern_version_id:
        return None
    installation = (
        await db.get(ERPInstallation, project.erp_installation_id)
        if project.erp_installation_id
        else None
    )
    if project.erp_installation_id and (
        not installation
        or installation.client_id != project.client_id
        or installation.erp_profile_id != project.erp_profile_id
    ):
        raise HTTPException(409, "pattern_project_installation_mismatch")
    pattern, version = await resolve_pattern(
        db,
        project.integration_pattern_version_id,
        profile_id=project.erp_profile_id,
        profile_version_id=project.erp_profile_version_id,
        allow_retired=True,
        installation=installation,
    )
    refs, snapshots = await baselines(db, version)
    contract = {
        "id": pattern.id,
        "key": pattern.key,
        "name": pattern.name,
        "provider": pattern.provider,
        "version_id": version.id,
        "version": version.version,
        "runtime_type": version.runtime_type,
        "direction": version.direction,
        "deliverable_type": version.deliverable_type,
        "qualification_strategy": version.qualification_strategy,
        "delivery_method": version.delivery_method,
        "profile_version_id": version.profile_version_id,
        "configuration": version.configuration,
        "baseline_versions": refs,
    }
    return {**contract, "contract_sha256": sha256(json_bytes(contract)), "baselines": snapshots}


async def pattern_bindings(db, project):
    if not project.integration_pattern_version_id:
        return {}
    context = await pattern_context(db, project)
    return {
        "integration_pattern_version_id": context["version_id"],
        "pattern_contract_sha256": context["contract_sha256"],
        "baseline_versions": context["baseline_versions"],
    }


def baseline_files(context):
    """Text source baselines use the existing named-file contract, not native claims."""
    files: dict[str, str] = {}
    for baseline in context.get("baselines", []):
        try:
            value = json.loads(baseline["content"])
        except json.JSONDecodeError:
            raise ValueError("baseline_named_file_contract_required") from None
        from app.services.packages import source_files

        extracted = source_files("BASELINE", value, {}, {})
        for name, data in extracted.items():
            if not name.startswith("artifacts/"):
                if name in files and files[name] != data:
                    raise ValueError("baseline_filename_collision")
                files[name] = data.decode("utf-8")
    if context.get("baselines") and not files:
        raise ValueError("baseline_named_files_required")
    return files


def apply_modifications(context, generated):
    if not isinstance(generated, list) or len(generated) > 100:
        raise ValueError("generated_named_files_required")
    files = baseline_files(context)
    rules = context["configuration"].get("generation_rules", {})
    allowed = set(rules.get("allowed_files", []))
    for item in generated:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "content"}
            or item["name"] not in allowed
            or not isinstance(item["content"], str)
        ):
            raise ValueError("baseline_modification_not_permitted")
        files[item["name"]] = item["content"]
    return [{"name": name, "content": content} for name, content in sorted(files.items())]


def validate_configuration(config):
    """Validate public pattern contracts at the administration trust boundary."""
    from app.schemas.identity import validate_public_configuration

    validate_public_configuration(config)
    for key in (
        "generation_rules",
        "compatibility",
        "adapter_bindings",
        "qualification_policy",
        "testing",
    ):
        if key in config and not isinstance(config[key], dict):
            raise ValueError(f"{key}_must_be_an_object")
    for key in ("required_capabilities", "optional_capabilities", "supported_environments"):
        values = config.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > 100
            or any(not isinstance(v, str) or not v for v in values)
        ):
            raise ValueError(f"{key}_must_be_a_string_list")
    for values in config.get("adapter_bindings", {}).values():
        if not isinstance(values, str) or not values:
            raise ValueError("adapter_binding_must_be_an_identifier")
    groups = (
        ("generation_rules", ("stages", "allowed_files", "allowed_modifications")),
        ("compatibility", ("editions", "product_versions")),
        ("qualification_policy", ("allowed_modes", "required_assurance")),
    )
    for group, keys in groups:
        for key in keys:
            values = config.get(group, {}).get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ValueError(f"{group}.{key}_must_be_a_string_list")
    rules = config.get("generation_rules", {})
    if "baseline_required" in rules and not isinstance(rules["baseline_required"], bool):
        raise ValueError("baseline_required_must_be_boolean")
    for key in ("strategy", "strategy_version"):
        if key in rules and (not isinstance(rules[key], str) or not rules[key]):
            raise ValueError(f"generation_rules.{key}_must_be_an_identifier")
    testing = config.get("testing", {})
    cases = testing.get("required_cases", [])
    from app.services.packages import approved_test_plan

    if (
        not isinstance(cases, list)
        or ("version" in testing and not isinstance(testing["version"], str))
        or (cases and not approved_test_plan(config))
    ):
        raise ValueError("invalid_pattern_test_plan")
    return config


async def validate_pattern_version(db, pattern, version):
    profile = await db.get(ERPProfileVersion, version.profile_version_id)
    if not profile or profile.profile_id != pattern.erp_profile_id or profile.status != "PUBLISHED":
        raise HTTPException(409, "published_product_intelligence_version_required")
    if (
        version.runtime_type not in RUNTIME_TYPES
        or version.qualification_strategy not in QUALIFICATION_STRATEGIES
    ):
        raise HTTPException(409, "invalid_pattern_runtime_or_qualification_strategy")
    config = version.configuration
    from app.services.codegen.strategies import get_strategy
    from app.services.packages import approved_test_plan

    try:
        validate_configuration(config)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    strategies = {
        "ERP_NATIVE": "NATIVE_ARTIFACT",
        "API_INTEGRATION": "REMOTE_API",
        "FILE_BASED": "FILE_EXCHANGE",
        "EXTERNAL_RUNTIME": "EXTERNAL_RUNTIME",
        "ASSISTED": "ASSISTED",
    }
    if version.qualification_strategy not in {strategies[version.runtime_type], "ASSISTED"}:
        raise HTTPException(409, "pattern_runtime_qualification_mismatch")
    rules = config.get("generation_rules", {})
    if rules.get("strategy"):
        try:
            strategy = get_strategy(rules["strategy"])
        except ValueError:
            raise HTTPException(409, "pattern_generation_strategy_not_installed") from None
        if rules.get("baseline_required", True) and not strategy.supports_baseline:
            raise HTTPException(409, "pattern_requires_a_baseline_modification_strategy")
        stages = {s["type"] for s in profile.configuration.get("workflow", {}).get("stages", [])}
        if (
            not rules.get("stages")
            or not set(rules["stages"]) <= stages
            or rules.get("strategy_version") != "1"
        ):
            raise HTTPException(409, "pattern_generation_stage_and_version_required")
        refs, snapshots = await baselines(db, version)
        if snapshots:
            try:
                baseline_files({"baselines": snapshots})
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
    if config.get("adapter_bindings") and not approved_test_plan(config):
        raise HTTPException(409, "pattern_test_plan_required")
    for key in ("required_capabilities", "supported_environments"):
        if not isinstance(config.get(key, []), list) or any(
            not isinstance(v, str) for v in config.get(key, [])
        ):
            raise HTTPException(409, "invalid_pattern_capability_or_environment_contract")


async def seed_pattern_definitions(db, profile, profile_version, definitions, actor):
    """Called only by explicit development seeding; never fill in existing patterns."""
    from datetime import UTC, datetime
    from uuid import NAMESPACE_URL, uuid5

    from app.models import AdminAuditEvent

    for definition in definitions:
        if await db.scalar(
            select(IntegrationPattern.id).where(
                IntegrationPattern.erp_profile_id == profile.id,
                IntegrationPattern.key == definition["key"],
            )
        ):
            continue
        pattern = IntegrationPattern(
            erp_profile_id=profile.id,
            provider="HighRadius",
            key=definition["key"],
            name=definition["name"],
            description=definition.get("description", ""),
            created_by=actor,
        )
        db.add(pattern)
        await db.flush()
        identifier = str(uuid5(NAMESPACE_URL, actor + ":" + pattern.key + ":baseline"))
        content = json.dumps(definition["baseline"]["content"], sort_keys=True)
        baseline = ERPAssetVersion(
            id=identifier,
            asset_id=identifier,
            profile_version_id=profile_version.id,
            asset_kind="PACKAGE",
            name=definition["baseline"]["name"],
            version=1,
            status="PUBLISHED",
            text_content=content,
            created_by=actor,
            metadata_json={"synthetic": True, "native_qualification": "NOT_VERIFIED"},
        )
        baseline.checksum = sha256(content.encode())
        db.add(baseline)
        version = IntegrationPatternVersion(
            pattern_id=pattern.id,
            profile_version_id=profile_version.id,
            version=1,
            created_by=actor,
            **{
                key: definition[key]
                for key in (
                    "runtime_type",
                    "direction",
                    "deliverable_type",
                    "qualification_strategy",
                    "delivery_method",
                    "configuration",
                )
            },
        )
        db.add(version)
        await db.flush()
        db.add(PatternBaseline(pattern_version_id=version.id, asset_version_id=baseline.id))
        await db.flush()
        await validate_pattern_version(db, pattern, version)
        version.status, version.published_at = "PUBLISHED", datetime.now(UTC)
        for action, entity in (
            ("FIXTURE_BASELINE_CREATED", baseline),
            ("FIXTURE_PATTERN_CREATED", pattern),
            ("FIXTURE_PATTERN_VERSION_PUBLISHED", version),
        ):
            db.add(
                AdminAuditEvent(
                    actor=actor,
                    action=action,
                    entity_type=type(entity).__name__,
                    entity_id=entity.id,
                    details={"synthetic": True},
                )
            )
