"""Durable generation commands and version-bound worker execution."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import ensure_project_mutation
from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    Artifact,
    ERPProfileVersion,
    GateStatus,
    GenerationRun,
    IdentitySubject,
    PlatformRoleAssignment,
    Project,
    ValidationCategory,
    ValidationResult,
    ValidationStatus,
)
from app.schemas import GenerateRequest
from app.security.access import get_authorized_project, resolved_identity
from app.security.identity import Identity, get_current_identity
from app.security.tenant_context import apply_tenant_context
from app.services.codegen.strategies import get_strategy
from app.services.llm.base import LLMProvider, LLMRequest, LLMResponse, safe_provider_receipt
from app.services.llm.factory import get_llm_provider
from app.services.ownership_audit import actor_subject, record_ownership_event
from app.services.project_revisions import lock_project
from app.services.prompt_compiler import (
    CompiledGenerationContext,
    PromptCompiler,
    PromptConfigurationError,
)
from app.services.validation import SchemaConformityValidator, TraceabilityValidator
from app.services.validation.strategies import get_validation_adapter
from app.services.workflow import WorkflowEngine, WorkflowError

logger = logging.getLogger("erpfusion.generation")
router = APIRouter(prefix="/api/projects", tags=["Generation"])


def job_response(run: GenerationRun) -> dict:
    return {
        "id": run.id,
        "stage": run.artifact_type,
        "status": run.status,
        "error_code": run.error_code,
        "artifact_version_id": run.artifact_version_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "model": run.model,
    }


@router.post("/{project_id}/generate", status_code=202)
async def trigger_generation(
    project_id: str,
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = await get_authorized_project(project_id, db, identity)
    actor = resolved_identity(identity)
    await ensure_project_mutation(db, actor, project)
    await lock_project(db, project)
    profile = await db.get(ERPProfileVersion, project.erp_profile_version_id)
    if profile is None:
        raise HTTPException(409, "Select a published ERP profile version")
    if len(project.business_requirement.strip()) < 10:
        raise HTTPException(409, "Upload or enter the requirement before generation")
    stage = body.stage.strip().upper()
    configured = WorkflowEngine.configured_stage_map(profile.configuration)
    if stage not in configured or stage not in profile.supported_artifact_types:
        raise HTTPException(400, "Stage is not supported by the pinned ERP profile")
    workflow = WorkflowEngine(db, actor_subject_id=await actor_subject(db, actor))
    try:
        await workflow.assert_can_generate(project.id, stage)
        adapter = configured[stage].get("adapter")
        if project.integration_pattern_version_id:
            from app.services.integration_patterns import pattern_context

            pattern = await pattern_context(db, project)
            rules = pattern["configuration"].get("generation_rules", {})
            if stage in rules.get("stages", []):
                adapter = rules.get("strategy")
        if not adapter:
            raise PromptConfigurationError("Configure a generation adapter for this stage")
        get_strategy(adapter)
        bindings = await workflow.current_bindings(project.id, stage)
        upstream = {}
        for name, version_id in bindings["upstream_artifacts"].items():
            version = await workflow.get_approved_version(project.id, name)
            if version is None or version.id != version_id:
                raise WorkflowError("An approved dependency is missing")
            upstream[name] = {
                "version_id": version.id,
                "version_number": version.version_number,
                "content": version.content,
            }
        task = configured[stage].get("task") or f"Generate the configured {stage} artifact."
        if body.execution_attempt_id:
            import json

            from app.models import ExecutionAttempt
            from app.services.packages import current_candidate

            attempt = await db.get(ExecutionAttempt, body.execution_attempt_id)
            _, candidate = await current_candidate(db, project)
            if (
                not attempt
                or attempt.project_id != project.id
                or attempt.client_id != project.client_id
                or not candidate
                or candidate.id != attempt.candidate_id
                or attempt.verdict == "PASSED"
                or attempt.status not in {"FAILED", "COMPLETED", "BLOCKED", "UNKNOWN_OUTCOME"}
            ):
                raise HTTPException(409, "applicable_failed_execution_required")
            if attempt.status == "UNKNOWN_OUTCOME" and not attempt.result.get(
                "reconciliation", {}
            ).get("safe_to_start_new_attempt"):
                raise HTTPException(409, "unknown_delivery_requires_human_reconciliation")
            task += "\nPropose a corrected engineering revision using this sanitized failure. "
            task += "Do not alter expected assertions, approvals, environment policy or evidence. "
            task += json.dumps(
                {"attempt_id": attempt.id, "failure": attempt.failure, "verdict": attempt.verdict}
            )
        compiled = await PromptCompiler(db).compile(project, stage, task, upstream)
        artifact = await workflow.start_generation(project.id, stage)
        run = GenerationRun(
            project_id=project.id,
            client_id=project.client_id,
            erp_installation_id=project.erp_installation_id,
            erp_environment_id=project.erp_environment_id,
            artifact_type=stage,
            profile_version_id=profile.id,
            model=settings.bedrock_model_id
            if settings.llm_provider == "bedrock"
            else settings.groq_model
            if settings.llm_provider == "groq"
            else "mock",
            actor_subject_id=await actor_subject(db, actor),
            status="QUEUED",
            resolved_context={
                "system_prompt": compiled.system_prompt,
                "user_prompt": compiled.user_prompt,
                "requirement": project.business_requirement,
                "schema_context": project.erp_schema_context,
                "upstream": upstream,
                "integration_pattern": compiled.integration_pattern,
            },
            provenance={
                **compiled.provenance,
                "adapter": adapter,
                "stage": stage,
                "input_bindings": bindings,
                "workflow_revision": project.workflow_revision,
                "artifact_id": artifact.id,
                "artifact_previous_version": artifact.current_version,
                "workflow_dependencies": configured[stage].get("depends_on", []),
                "remediation_execution_attempt_id": body.execution_attempt_id,
            },
        )
        db.add(run)
        await db.flush()
        await record_ownership_event(
            db,
            actor,
            "GENERATION_QUEUED",
            "GenerationRun",
            run.id,
            client_id=project.client_id,
            details={"stage": stage},
        )
        return job_response(run)
    except (WorkflowError, PromptConfigurationError, ValueError) as error:
        raise HTTPException(409, str(error)) from None


@router.get("/{project_id}/generation-jobs")
async def list_jobs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> list[dict]:
    project = await get_authorized_project(project_id, db, identity)
    runs = (
        await db.scalars(
            select(GenerationRun)
            .where(
                GenerationRun.project_id == project.id,
                GenerationRun.client_id.is_not_distinct_from(project.client_id),
            )
            .order_by(GenerationRun.created_at.desc())
            .limit(100)
        )
    ).all()
    return [job_response(run) for run in runs]


@router.get("/{project_id}/generation-jobs/{run_id}")
async def get_job(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
) -> dict:
    project = await get_authorized_project(project_id, db, identity)
    run = await db.get(GenerationRun, run_id)
    if run is None or run.project_id != project.id or run.client_id != project.client_id:
        raise HTTPException(404, "Generation job not found")
    return job_response(run)


class RecordedProvider(LLMProvider):
    """Keep effective requests/receipts in authorized provenance, never ordinary logs."""

    def __init__(self, provider):
        self.provider = provider
        self.model = getattr(provider, "model", "unknown")
        self.requests = []
        self.receipts = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request.model_dump())
        response = await self.provider.generate(request)
        self.receipts.append(
            safe_provider_receipt(
                response.raw_response or {"model": response.model, "usage": response.usage}
            )
        )
        return response

    async def generate_json(self, request: LLMRequest) -> dict[str, Any]:
        if hasattr(self.provider, "generate"):
            return await super().generate_json(request)
        self.requests.append(request.model_dump())
        return await self.provider.generate_json(request)

    def __getattr__(self, name):
        if name == "generate_configured_json" and hasattr(self.provider, name):

            async def configured(request):
                self.requests.append(request.model_dump())
                return await self.provider.generate_configured_json(request)

            return configured
        raise AttributeError(name)


async def authorize_job(
    db: AsyncSession, run: GenerationRun, project: Project, settings: Settings
) -> bool:
    if settings.auth_mode == "development" and not settings.is_production:
        return True
    subject = await db.scalar(
        select(IdentitySubject).where(
            IdentitySubject.id == run.actor_subject_id, IdentitySubject.status == "ACTIVE"
        )
    )
    if subject is None:
        return False
    # Preserve the worker's provisioned client scope; set only the actor for role reads.
    context = db.info.get("erpfusion_tenant_context")
    if context:
        await apply_tenant_context(
            db,
            client_ids=context.client_ids,
            client_admin_ids=context.client_admin_ids,
            subject_id=subject.id,
            is_platform_admin=context.is_platform_admin,
            is_erp_admin=context.is_erp_admin,
            allow_unowned_legacy=context.allow_unowned_legacy,
        )
    roles = await db.scalars(
        select(PlatformRoleAssignment.role).where(
            PlatformRoleAssignment.subject_id == subject.id,
            PlatformRoleAssignment.status == "ACTIVE",
        )
    )
    actor = Identity(
        user_id=subject.subject,
        issuer=subject.issuer,
        subject_id=subject.id,
        roles=frozenset(role.lower() for role in roles),
    )
    try:
        await get_authorized_project(project.id, db, actor, allow_legacy_fixture=False)
        await ensure_project_mutation(db, actor, project)
        return True
    except HTTPException:
        return False


async def process_generation_run(
    db: AsyncSession, run_id: str, *, settings: Settings | None = None, provider=None
) -> dict:
    """Claim atomically, commit before LLM work, reject stale results on completion."""
    settings = settings or get_settings()
    claim = await db.execute(
        update(GenerationRun)
        .where(GenerationRun.id == run_id, GenerationRun.status == "QUEUED")
        .values(status="RUNNING", started_at=datetime.now(UTC))
        .returning(GenerationRun.id)
    )
    if claim.scalar_one_or_none() is None:
        run = await db.get(GenerationRun, run_id)
        return job_response(run) if run else {"status": "NOT_FOUND"}
    await db.commit()
    run = await db.get(GenerationRun, run_id)
    if run is None:
        return {"status": "NOT_FOUND"}
    project = await db.get(Project, run.project_id)
    profile = await db.get(ERPProfileVersion, run.profile_version_id)
    if project:
        await lock_project(db, project)
        await db.refresh(run)
    if (
        not project
        or not profile
        or project.archived_at
        or run.status != "RUNNING"
        or project.workflow_revision != run.provenance["workflow_revision"]
        or not await authorize_job(db, run, project, settings)
    ):
        was_running = run.status == "RUNNING"
        run.status, run.error_code = "STALE", "PROJECT_OR_AUTHORIZATION_UNAVAILABLE"
        if project and was_running:
            artifact = await db.get(Artifact, run.provenance["artifact_id"])
            if artifact and artifact.gate_status == GateStatus.GENERATING:
                artifact.gate_status = GateStatus.LOCKED
                project.workflow_status = "BLOCKED"
        run.completed_at = datetime.now(UTC)
        await db.commit()
        return job_response(run)
    # All inputs were compiled at enqueue time. No retrieval or provider fallback here.
    frozen_project = Project(
        id=project.id,
        client_id=project.client_id,
        business_requirement=run.resolved_context["requirement"],
        erp_schema_context=run.resolved_context["schema_context"],
        erp_profile_version_id=profile.id,
        name=project.name,
        integration_pattern_version_id=project.integration_pattern_version_id,
    )
    compiled = CompiledGenerationContext(
        run.resolved_context["system_prompt"],
        run.resolved_context["user_prompt"],
        run.provenance,
        profile,
        run.resolved_context.get("integration_pattern"),
    )
    upstream = run.resolved_context["upstream"]
    llm = None
    await db.commit()
    try:
        llm = RecordedProvider(provider or get_llm_provider(settings))
        content = await get_strategy(run.provenance["adapter"]).generate(
            frozen_project, run.artifact_type, upstream, compiled, llm
        )
        project = await lock_project(db, project)
        await db.refresh(run)
        workflow = WorkflowEngine(db, actor_subject_id=run.actor_subject_id)
        artifact = await db.get(Artifact, run.provenance["artifact_id"])
        run.output_content = content
        run.model = llm.model
        run.resolved_context = {**run.resolved_context, "effective_provider_requests": llm.requests}
        run.provenance = {**run.provenance, "provider_receipts": llm.receipts}
        was_running = run.status == "RUNNING"
        if (
            not was_running
            or project.archived_at
            or not await authorize_job(db, run, project, settings)
            or project.workflow_revision != run.provenance["workflow_revision"]
            or run.provenance["input_bindings"]
            != await workflow.current_bindings(project.id, run.artifact_type)
            or artifact is None
            or artifact.gate_status != GateStatus.GENERATING
            or artifact.current_version != run.provenance["artifact_previous_version"]
        ):
            run.status, run.error_code = "STALE", "UPSTREAM_REVISION_CHANGED"
            if was_running and artifact and artifact.gate_status == GateStatus.GENERATING:
                artifact.gate_status = GateStatus.LOCKED
                project.workflow_status = "BLOCKED"
        else:
            validations = await _run_validators(
                db, artifact.id, run.artifact_type, content, frozen_project, profile, compiled
            )
            failed = any(item["status"] == ValidationStatus.FAIL for item in validations)
            version = await workflow.complete_generation(
                artifact,
                content,
                llm.model,
                {
                    **run.provenance,
                    "requirement": frozen_project.business_requirement,
                    "schema_context": frozen_project.erp_schema_context,
                    "profile_configuration": profile.configuration,
                    "generation_run_id": run.id,
                },
                generation_run_id=run.id,
            )
            for item in validations:
                db.add(
                    ValidationResult(
                        artifact_version_id=version.id,
                        client_id=project.client_id,
                        category=item["category"],
                        status=item["status"],
                        checks=item["checks"],
                    )
                )
            run.artifact_version_id = version.id
            run.status = "VALIDATION_FAILED" if failed else "COMPLETED"
            if failed:
                artifact.gate_status = GateStatus.LOCKED
                project.workflow_status = "BLOCKED"
            else:
                await workflow.mark_validated(version)
        run.completed_at = datetime.now(UTC)
        await db.commit()
    except Exception as error:
        await db.rollback()
        run = await db.get(GenerationRun, run_id)
        if run is None:
            return {"status": "NOT_FOUND"}
        project = await db.get(Project, run.project_id)
        if project:
            await lock_project(db, project)
            await db.refresh(run)
        if run.status == "RUNNING":
            code = str(error)
            permitted = (
                "BEDROCK_",
                "LLM_OUTPUT_",
                "GROQ_",
                "MOCK_PROVIDER_",
                "DEMO_MODE_",
                "LLM_PROVIDER_",
            )
            run.error_code = (
                code
                if code.startswith(permitted)
                and len(code) <= 80
                and all(
                    character.isupper() or character.isdigit() or character in "_: ;"
                    for character in code
                )
                else "GENERATION_FAILED"
            )
            run.status, run.completed_at = "FAILED", datetime.now(UTC)
            artifact = await db.get(Artifact, run.provenance["artifact_id"])
            if artifact and artifact.gate_status == GateStatus.GENERATING:
                artifact.gate_status = GateStatus.LOCKED
            if project:
                project.workflow_status = "BLOCKED"
            if llm:
                run.resolved_context = {
                    **run.resolved_context,
                    "effective_provider_requests": llm.requests,
                }
                run.provenance = {**run.provenance, "provider_receipts": llm.receipts}
            await db.commit()
        logger.warning("Generation job failed job_id=%s code=%s", run.id, run.error_code)
    return job_response(run)


async def _run_validators(db, artifact_id, stage, content, project, profile, compiled):
    results: list[dict] = []
    validation_config = profile.configuration.get("validation", {})
    if validation_config.get("schema_conformity", True):
        outcome, checks = SchemaConformityValidator.validate(
            stage, content, project.erp_schema_context
        )
        results.append({"category": ValidationCategory.SCHEMA, "status": outcome, "checks": checks})
    adapter = validation_config.get("adapters", {}).get(stage)
    if adapter:
        validator, category = get_validation_adapter(adapter)
        outcome, checks = validator(content)
        results.append({"category": category, "status": outcome, "checks": checks})

    for rule in validation_config.get("rules", []):
        if not isinstance(rule, dict) or rule.get("stage") not in (None, stage):
            continue
        check = _evaluate_rule(rule, content)
        outcome = ValidationStatus.PASS if check["passed"] else ValidationStatus.FAIL
        results.append(
            {
                "category": ValidationCategory.MAPPING,
                "status": outcome,
                "checks": [
                    {
                        "name": rule.get("name", "configured_rule"),
                        "status": outcome.value,
                        "message": check["message"],
                        "details": {"rule": rule},
                    }
                ],
            }
        )

    # Traceability behavior is selected in the profile; the default checker is workflow-generic.
    if validation_config.get("cross_artifact_traceability"):
        if validation_config.get("traceability_adapter") == "oracle_attribute_lineage":
            workflow = WorkflowEngine(db)
            fdd = (
                content
                if stage == "FDD"
                else await workflow.get_approved_content(project.id, "FDD")
            )
            tdd = (
                content
                if stage == "TDD"
                else await workflow.get_approved_content(project.id, "TDD")
            )
            sql = (
                content
                if stage == "SQL"
                else await workflow.get_approved_content(project.id, "SQL")
            )
            if fdd:
                outcome, checks, _ = TraceabilityValidator.validate_traceability(
                    fdd, tdd or {}, sql or {}
                )
                results.append(
                    {
                        "category": ValidationCategory.CROSS_ARTIFACT,
                        "status": outcome,
                        "checks": checks,
                    }
                )
        else:
            stage_config = WorkflowEngine.configured_stage_map(
                compiled.profile_version.configuration
            ).get(stage, {})
            dependencies = stage_config.get("depends_on", [])
            missing = [
                dependency
                for dependency in dependencies
                if dependency not in compiled.provenance.get("upstream_artifacts", {})
            ]
            outcome = ValidationStatus.FAIL if missing else ValidationStatus.PASS
            results.append(
                {
                    "category": ValidationCategory.CROSS_ARTIFACT,
                    "status": outcome,
                    "checks": [
                        {
                            "name": "configured_dependency_traceability",
                            "status": outcome.value,
                            "message": f"Missing approved upstream artifacts: {missing}"
                            if missing
                            else f"All configured dependencies are represented: {dependencies}.",
                            "details": {
                                "dependencies": dependencies,
                                "upstream_versions": compiled.provenance.get(
                                    "upstream_artifacts", {}
                                ),
                            },
                        }
                    ],
                }
            )

    # Validation rows are linked to the artifact version after it is created.
    return results


def _evaluate_rule(rule: dict, content: dict) -> dict:
    kind = rule.get("type")
    if kind == "required_keys":
        missing = [key for key in rule.get("keys", []) if key not in content]
        return {
            "passed": not missing,
            "message": "Required output fields present."
            if not missing
            else f"Missing required output fields: {missing}",
        }
    if kind == "regex":
        import re

        target = str(content.get(rule.get("field", ""), ""))
        matched = bool(re.search(rule.get("pattern", "(?!)"), target))
        return {
            "passed": matched,
            "message": "Configured pattern matched."
            if matched
            else "Configured pattern did not match.",
        }
    if kind == "max_length":
        target = str(content.get(rule.get("field", ""), ""))
        passed = len(target) <= int(rule.get("maximum", 0))
        return {
            "passed": passed,
            "message": "Configured length limit passed."
            if passed
            else "Configured length limit exceeded.",
        }
    return {"passed": False, "message": f"Unsupported validation rule type: {kind}"}
