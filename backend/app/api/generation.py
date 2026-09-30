"""ERP-agnostic generation route driven by the request's pinned profile version."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    ERPProfileVersion, GenerationRun, GateStatus, Project, ValidationCategory,
    ValidationResult, ValidationStatus, VersionState,
)
from app.schemas import ArtifactVersionResponse, GenerateRequest
from app.services.codegen.strategies import get_strategy
from app.services.prompt_compiler import PromptCompiler, PromptConfigurationError
from app.services.validation import SchemaConformityValidator, TraceabilityValidator
from app.services.validation.strategies import get_validation_adapter
from app.services.workflow import WorkflowEngine, WorkflowError
from app.services.llm.factory import get_llm_provider

logger = logging.getLogger("erpfusion.api.generation")
router = APIRouter(prefix="/api/projects", tags=["Generation"])


@router.post("/{project_id}/generate", response_model=ArtifactVersionResponse)
async def trigger_generation(
    project_id: str, body: GenerateRequest, db: AsyncSession = Depends(get_db)
) -> ArtifactVersionResponse:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    if not project.erp_profile_version_id:
        raise HTTPException(status_code=409, detail="This request has no pinned ERP profile version. Create a request with a published profile.")
    profile = await db.get(ERPProfileVersion, project.erp_profile_version_id)
    if profile is None:
        raise HTTPException(status_code=409, detail="The pinned ERP profile version is unavailable.")

    stage = body.stage.strip().upper()
    configured = WorkflowEngine.configured_stage_map(profile.configuration)
    if stage not in configured or stage not in profile.supported_artifact_types:
        raise HTTPException(status_code=400, detail=f"Stage {stage} is not supported by the selected ERP profile version.")

    workflow = WorkflowEngine(db)
    try:
        artifact = await workflow.start_generation(project_id, stage)
        upstream = {}
        dependencies = set()
        pending = list(configured[stage].get("depends_on", []))
        while pending:
            dependency = pending.pop()
            if dependency in dependencies:
                continue
            dependencies.add(dependency)
            pending.extend(configured.get(dependency, {}).get("depends_on", []))
        for upstream_stage in configured:
            if upstream_stage not in dependencies:
                continue
            version = await workflow.get_approved_version(project_id, upstream_stage)
            if version:
                upstream[upstream_stage] = {
                    "version_id": version.id, "version_number": version.version_number,
                    "content": version.content,
                }

        adapter = configured[stage].get("adapter")
        if not adapter:
            raise PromptConfigurationError(f"No generation adapter is configured for stage {stage}.")
        task = configured[stage].get("task") or f"Generate the {stage} artifact using the approved request inputs and profile configuration."
        compiled = await PromptCompiler(db).compile(project, stage, task, upstream)
        llm = get_llm_provider()
        model_name = getattr(llm, "model", "unknown")
        generated_content = await get_strategy(adapter).generate(project, stage, upstream, compiled, llm)

        validation_results = await _run_validators(db, artifact.id, stage, generated_content,
                                                   project, profile, compiled)
        has_failures = any(result["status"] == ValidationStatus.FAIL for result in validation_results)
        run = GenerationRun(
            project_id=project.id, artifact_type=stage, profile_version_id=profile.id, model=model_name,
            resolved_context={"system_prompt": compiled.system_prompt, "user_prompt": compiled.user_prompt},
            provenance={**compiled.provenance, "adapter": adapter, "stage": stage,
                        "workflow_dependencies": configured[stage].get("depends_on", [])},
            status="VALIDATION_FAILED" if has_failures else "COMPLETED",
        )
        db.add(run)
        await db.flush()
        snapshot = {
            **compiled.provenance,
            "workflow_dependencies": configured[stage].get("depends_on", []),
            "profile_configuration": profile.configuration,
            "requirement": project.business_requirement,
            "schema_context": project.erp_schema_context,
            "adapter": adapter,
            "model": model_name,
            "generation_run_id": run.id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        version = await workflow.complete_generation(
            artifact, generated_content, model_name, snapshot, generation_run_id=run.id,
        )
        for result in validation_results:
            db.add(ValidationResult(artifact_version_id=version.id, category=result["category"],
                                    status=result["status"], checks=result["checks"]))
        if has_failures:
            artifact.gate_status = GateStatus.LOCKED
            run.status = "VALIDATION_FAILED"
            await db.flush()
        else:
            await workflow.mark_validated(version)
        return ArtifactVersionResponse.model_validate(version)
    except (WorkflowError, PromptConfigurationError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Generation failed for project %s stage %s", project_id, stage)
        await db.rollback()
        raise HTTPException(status_code=500, detail="Generation failed. Check server logs for details.") from exc


async def _run_validators(db, artifact_id, stage, content, project, profile, compiled):
    results: list[dict] = []
    validation_config = profile.configuration.get("validation", {})
    if validation_config.get("schema_conformity", True):
        outcome, checks = SchemaConformityValidator.validate(stage, content, project.erp_schema_context)
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
        results.append({"category": ValidationCategory.MAPPING, "status": outcome,
                        "checks": [{"name": rule.get("name", "configured_rule"),
                                            "status": outcome.value, "message": check["message"],
                                            "details": {"rule": rule}}]})

    # Traceability behavior is selected in the profile; the default checker is workflow-generic.
    if validation_config.get("cross_artifact_traceability"):
        if validation_config.get("traceability_adapter") == "oracle_attribute_lineage":
            workflow = WorkflowEngine(db)
            fdd = content if stage == "FDD" else await workflow.get_approved_content(project.id, "FDD")
            tdd = content if stage == "TDD" else await workflow.get_approved_content(project.id, "TDD")
            sql = content if stage == "SQL" else await workflow.get_approved_content(project.id, "SQL")
            if fdd:
                outcome, checks, _ = TraceabilityValidator.validate_traceability(fdd, tdd or {}, sql or {})
                results.append({"category": ValidationCategory.CROSS_ARTIFACT, "status": outcome, "checks": checks})
        else:
            stage_config = WorkflowEngine.configured_stage_map(compiled.profile_version.configuration).get(stage, {})
            dependencies = stage_config.get("depends_on", [])
            missing = [dependency for dependency in dependencies if dependency not in compiled.provenance.get("upstream_artifacts", {})]
            outcome = ValidationStatus.FAIL if missing else ValidationStatus.PASS
            results.append({"category": ValidationCategory.CROSS_ARTIFACT, "status": outcome,
                            "checks": [{"name": "configured_dependency_traceability", "status": outcome.value,
                                        "message": f"Missing approved upstream artifacts: {missing}" if missing else
                                                   f"All configured dependencies are represented: {dependencies}.",
                                        "details": {"dependencies": dependencies,
                                                    "upstream_versions": compiled.provenance.get("upstream_artifacts", {})}}]})

    # Validation rows are linked to the artifact version after it is created.
    return results


def _evaluate_rule(rule: dict, content: dict) -> dict:
    kind = rule.get("type")
    if kind == "required_keys":
        missing = [key for key in rule.get("keys", []) if key not in content]
        return {"passed": not missing, "message": "Required output fields present." if not missing else f"Missing required output fields: {missing}"}
    if kind == "regex":
        import re
        target = str(content.get(rule.get("field", ""), ""))
        matched = bool(re.search(rule.get("pattern", "(?!)"), target))
        return {"passed": matched, "message": "Configured pattern matched." if matched else "Configured pattern did not match."}
    if kind == "max_length":
        target = str(content.get(rule.get("field", ""), ""))
        passed = len(target) <= int(rule.get("maximum", 0))
        return {"passed": passed, "message": "Configured length limit passed." if passed else "Configured length limit exceeded."}
    return {"passed": False, "message": f"Unsupported validation rule type: {kind}"}
