"""Explicit, versioned development fixtures for the ERP registry.

This module is never called by startup or a read endpoint. Existing resources
are skipped as a whole: fixture loading cannot republish, repair, overwrite, or
reactivate an administrator's configuration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdminAuditEvent,
    ERPProfile,
    ERPProfileVersion,
    Project,
    ProjectStatus,
    PromptVersion,
)
from app.services.workflow import WorkflowEngine

LifecycleStatus = Literal["DRAFT", "REVIEW", "PUBLISHED", "RETIRED"]


class FixturePrompt(BaseModel):
    """One immutable prompt resource included in a development manifest."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    scope: Literal["ERP", "STAGE"]
    stage: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: LifecycleStatus
    variables: list[str] = Field(default_factory=list)


class FixtureProfileVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    status: LifecycleStatus
    supported_artifact_types: list[str]
    configuration: dict[str, Any]
    prompts: list[FixturePrompt] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stage_prompts(self) -> FixtureProfileVersion:
        workflow = self.configuration.get("workflow", {})
        if not isinstance(workflow, dict):
            raise ValueError("A fixture workflow must be an object")
        stages = workflow.get("stages", [])
        if not isinstance(stages, list) or not stages:
            raise ValueError("A fixture workflow needs a nonempty stage list")
        configured: list[str] = []
        for stage in stages:
            if not isinstance(stage, dict) or not isinstance(stage.get("type"), str):
                raise ValueError("Fixture stages need a string type")
            if not stage["type"] or len(stage["type"]) > 80:
                raise ValueError("Fixture stage names must be between 1 and 80 characters")
            dependencies = stage.get("depends_on", [])
            if not isinstance(dependencies, list) or any(
                not isinstance(dependency, str) for dependency in dependencies
            ):
                raise ValueError("Fixture dependencies must be stage names")
            configured.append(stage["type"])
        if any(
            dependency not in configured
            for stage in stages
            for dependency in stage.get("depends_on", [])
        ):
            raise ValueError("Fixture dependencies must reference configured stages")
        if len(set(configured)) != len(configured):
            raise ValueError("A fixture workflow must not repeat stage names")
        if set(configured) != set(self.supported_artifact_types):
            raise ValueError("Fixture artifact types must match its workflow stages")
        if self.status == "PUBLISHED":
            published_stages = {
                prompt.stage for prompt in self.prompts if prompt.status == "PUBLISHED"
            }
            required = {stage.get("prompt_stage", stage["type"]) for stage in stages}
            if not required.issubset(published_stages):
                raise ValueError("Published fixtures need published prompts for every stage")
        return self


class FixtureProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    business_requirement: str = Field(min_length=1)
    erp_schema_context: dict[str, Any]


class FixtureProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    vendor: str = Field(min_length=1, max_length=255)
    product_version: str | None = None
    description: str | None = None
    status: LifecycleStatus
    configuration: dict[str, Any]
    profile_version: FixtureProfileVersion
    sample_projects: list[FixtureProject] = Field(default_factory=list)
    integration_patterns: list[dict[str, Any]] = Field(default_factory=list)


class FixtureManifest(BaseModel):
    """Versioned data, rather than an ERP-specific generation registry."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    version: int = Field(ge=1)
    description: str
    profiles: list[FixtureProfile]

    @model_validator(mode="after")
    def validate_unique_keys(self) -> FixtureManifest:
        keys = [profile.key for profile in self.profiles]
        if len(set(keys)) != len(keys):
            raise ValueError("Fixture profile keys must be unique")
        for profile in self.profiles:
            if profile.status != profile.profile_version.status:
                raise ValueError("Fixture profile and initial version lifecycle must agree")
            prompt_keys = [
                (prompt.scope, prompt.name, prompt.version)
                for prompt in profile.profile_version.prompts
            ]
            if len(set(prompt_keys)) != len(prompt_keys):
                raise ValueError("Fixture prompt resource versions must be unique")
        return self


class SeedReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_id: str
    manifest_version: int
    manifest_checksum: str
    profiles_created: int
    profiles_skipped: int
    prompts_created: int
    projects_created: int
    projects_skipped: int


def read_fixture_manifest(name: str = "development-v1") -> FixtureManifest:
    """Read a packaged manifest by a bounded identifier, without directory traversal."""
    if (
        not name
        or len(name) > 80
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name)
    ):
        raise ValueError("Invalid fixture manifest identifier")
    payload = files("app.cli").joinpath("fixtures", f"{name}.json").read_text(encoding="utf-8")
    manifest = FixtureManifest.model_validate_json(payload)
    if manifest.manifest_id != name:
        raise ValueError("Fixture manifest identifier does not match its file")
    return manifest


async def load_development_fixtures(
    db: AsyncSession,
    *,
    manifest: FixtureManifest,
    app_env: str,
    include_sample_projects: bool = False,
) -> SeedReport:
    """Add missing development fixtures inside the caller's transaction.

    No schema operations or commit occur here. Existing profiles and their
    versions/prompts are intentionally never modified or filled in. Pattern
    fixtures can explicitly add a separate intelligence version. Sample
    requests have deterministic IDs and are limited to the exact seed-owned,
    published profile revision. Production use is rejected before any SQL.
    """
    if app_env != "development":
        raise ValueError("Development fixtures are disabled outside APP_ENV=development")

    checksum = hashlib.sha256(
        json.dumps(manifest.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    actor = f"fixture:{manifest.manifest_id}"
    profiles_created = profiles_skipped = prompts_created = 0
    projects_created = projects_skipped = 0

    for definition in manifest.profiles:
        profile = (
            await db.execute(select(ERPProfile).where(ERPProfile.key == definition.key))
        ).scalar_one_or_none()
        profile_version: ERPProfileVersion | None
        if profile is None:
            profile = ERPProfile(
                **definition.model_dump(
                    exclude={"profile_version", "sample_projects", "integration_patterns"}
                ),
                active=definition.status != "RETIRED",
                created_by=actor,
                updated_by=actor,
            )
            db.add(profile)
            await db.flush()
            version_definition = definition.profile_version
            profile_version = ERPProfileVersion(
                profile_id=profile.id,
                **version_definition.model_dump(exclude={"prompts"}),
                published_at=(
                    datetime.now(UTC) if version_definition.status == "PUBLISHED" else None
                ),
                created_by=actor,
                updated_by=actor,
            )
            db.add(profile_version)
            await db.flush()
            profiles_created += 1
            _record_fixture_event(
                db,
                actor,
                "FIXTURE_PROFILE_CREATED",
                "ERP_PROFILE",
                str(profile.id),
                manifest,
                checksum,
            )
            _record_fixture_event(
                db,
                actor,
                "FIXTURE_VERSION_CREATED",
                "ERP_PROFILE_VERSION",
                str(profile_version.id),
                manifest,
                checksum,
            )
            for prompt_definition in version_definition.prompts:
                prompt = PromptVersion(
                    profile_version_id=profile_version.id,
                    **prompt_definition.model_dump(),
                    created_by=actor,
                    updated_by=actor,
                )
                db.add(prompt)
                await db.flush()
                prompts_created += 1
                _record_fixture_event(
                    db,
                    actor,
                    "FIXTURE_PROMPT_CREATED",
                    "PROMPT_VERSION",
                    str(prompt.id),
                    manifest,
                    checksum,
                )
        else:
            profiles_skipped += 1
            profile_version = (
                await db.execute(
                    select(ERPProfileVersion).where(
                        ERPProfileVersion.profile_id == profile.id,
                        ERPProfileVersion.version == definition.profile_version.version,
                    )
                )
            ).scalar_one_or_none()

        if definition.integration_patterns:
            # Explicit pattern fixtures may ADD an intelligence version. They
            # never change an existing product/profile version, prompt or asset.
            if (
                not profile_version
                or profile_version.created_by != actor
                or profile_version.configuration != definition.profile_version.configuration
            ):
                from sqlalchemy import func

                fixture_versions = await db.scalars(
                    select(ERPProfileVersion)
                    .where(
                        ERPProfileVersion.profile_id == profile.id,
                        ERPProfileVersion.created_by == actor,
                    )
                    .order_by(ERPProfileVersion.version.desc())
                )
                profile_version = next(
                    (
                        v
                        for v in fixture_versions
                        if v.status == "PUBLISHED"
                        and v.updated_by == actor
                        and v.configuration == definition.profile_version.configuration
                        and v.supported_artifact_types
                        == definition.profile_version.supported_artifact_types
                    ),
                    None,
                )
                if profile_version is None:
                    number = (
                        await db.scalar(
                            select(func.max(ERPProfileVersion.version)).where(
                                ERPProfileVersion.profile_id == profile.id
                            )
                        )
                        or 0
                    ) + 1
                    profile_version = ERPProfileVersion(
                        profile_id=profile.id,
                        **definition.profile_version.model_dump(exclude={"prompts", "version"}),
                        version=number,
                        created_by=actor,
                        updated_by=actor,
                        published_at=datetime.now(UTC),
                    )
                    db.add(profile_version)
                    await db.flush()
                    for prompt_definition in definition.profile_version.prompts:
                        db.add(
                            PromptVersion(
                                profile_version_id=profile_version.id,
                                **prompt_definition.model_dump(),
                                created_by=actor,
                                updated_by=actor,
                            )
                        )
                        prompts_created += 1
                    _record_fixture_event(
                        db,
                        actor,
                        "FIXTURE_VERSION_CREATED",
                        "ERP_PROFILE_VERSION",
                        profile_version.id,
                        manifest,
                        checksum,
                    )
            from app.services.integration_patterns import seed_pattern_definitions

            await seed_pattern_definitions(
                db, profile, profile_version, definition.integration_patterns, actor
            )
        if not include_sample_projects:
            continue
        for sample in definition.sample_projects:
            if (
                not profile.active
                or profile.status != "PUBLISHED"
                or profile.created_by != actor
                or profile_version is None
                or profile_version.status != "PUBLISHED"
                or profile_version.created_by != actor
                or profile_version.updated_by != actor
                or profile.updated_by != actor
            ):
                projects_skipped += 1
                continue
            project_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"erpfusion:{manifest.manifest_id}:{definition.key}:{sample.name}",
                )
            )
            if await db.get(Project, project_id) is not None:
                projects_skipped += 1
                continue
            project = Project(
                id=project_id,
                **sample.model_dump(),
                erp_profile_id=profile.id,
                erp_profile_version_id=profile_version.id,
                status=ProjectStatus.ACTIVE,
            )
            db.add(project)
            await db.flush()
            await WorkflowEngine(db).initialize_project_artifacts(project)
            projects_created += 1
            _record_fixture_event(
                db, actor, "FIXTURE_PROJECT_CREATED", "PROJECT", str(project.id), manifest, checksum
            )

    await db.flush()
    return SeedReport(
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.version,
        manifest_checksum=checksum,
        profiles_created=profiles_created,
        profiles_skipped=profiles_skipped,
        prompts_created=prompts_created,
        projects_created=projects_created,
        projects_skipped=projects_skipped,
    )


def _record_fixture_event(
    db: AsyncSession,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    manifest: FixtureManifest,
    checksum: str,
) -> None:
    db.add(
        AdminAuditEvent(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details={
                "manifest_id": manifest.manifest_id,
                "manifest_version": manifest.version,
                "manifest_checksum": checksum,
            },
        )
    )
