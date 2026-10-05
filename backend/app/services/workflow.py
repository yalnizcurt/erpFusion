"""
HighStudio — Workflow Engine

Orchestrates the artifact generation pipeline with strict gate enforcement.

Key responsibilities:
  1. Enforce stage ordering (no stage may proceed until upstream is APPROVED).
  2. Manage artifact state transitions (DRAFT → AI_VALIDATED → PENDING_REVIEW → APPROVED).
  3. Cascade dependency invalidation when upstream artifacts change.
  4. Create audit entries for every lifecycle event.

Stage order, dependencies and review roles come from the pinned ERP profile.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Artifact,
    ArtifactVersion,
    AuditAction,
    AuditEntry,
    ERPProfileVersion,
    GateStatus,
    Project,
    VersionState,
)


class WorkflowError(Exception):
    """Raised when a workflow rule is violated."""

    pass


class WorkflowEngine:
    """
    Manages the artifact generation workflow with gate enforcement.

    All methods require an active database session.
    """

    def __init__(self, db: AsyncSession, *, actor_subject_id: str | None = None):
        self.db = db
        self.actor_subject_id = actor_subject_id

    @staticmethod
    def _stage_name(artifact_type: str | Enum) -> str:
        """Normalize legacy enum values and data-defined stage strings."""
        return str(artifact_type.value) if isinstance(artifact_type, Enum) else str(artifact_type)

    @staticmethod
    def configured_review_role(stage_name: str, stage_config: dict[str, Any]) -> str:
        return str(
            stage_config.get("review_role")
            or (
                "FUNCTIONAL_REVIEWER"
                if stage_name in {"CONTEXT_ANALYSIS", "FDD"}
                else "TECHNICAL_REVIEWER"
            )
        )

    @staticmethod
    def configured_stage_map(configuration: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Return configured stages with their declared dependencies plus strict sequence order."""
        stage_list = configuration.get("workflow", {}).get("stages", [])
        result: dict[str, dict[str, Any]] = {}
        previous_stage = None
        for item in stage_list:
            if not isinstance(item, dict) or not item.get("type"):
                continue
            stage = dict(item)
            dependencies = list(stage.get("depends_on", []))
            if previous_stage and previous_stage not in dependencies:
                dependencies.insert(0, previous_stage)
            stage["depends_on"] = dependencies
            result[stage["type"]] = stage
            previous_stage = stage["type"]
        return result

    @staticmethod
    def review_blockers(content: dict[str, Any]) -> list[str]:
        """Recognize unresolved questions in current and legacy assessment contracts."""
        blockers = []
        if content.get("requirements_clear", content.get("is_clear")) is False:
            blockers.append("The requirement assessment is not clear.")
        for field in ("blocking_questions", "missing_information", "ambiguities"):
            questions = content.get(field) or []
            for item in questions if isinstance(questions, list) else [questions]:
                if isinstance(item, dict):
                    if item.get("resolved") is True or item.get("blocking") is False:
                        continue
                    message = item.get("question") or item.get("description") or field
                else:
                    message = str(item)
                if message:
                    blockers.append(str(message))
        assumptions = content.get("assumptions") or []
        for assumption in assumptions if isinstance(assumptions, list) else [assumptions]:
            if isinstance(assumption, dict) and assumption.get("needs_confirmation") is True:
                blockers.append(str(assumption.get("description") or "Confirm the assumption."))
        return list(dict.fromkeys(blockers))

    # ── Initialization ────────────────────────────────────────

    async def initialize_project_artifacts(self, project: Project) -> list[Artifact]:
        """
        Create all artifact records for a new project.

        The first stage (CONTEXT_ANALYSIS) is set to LOCKED but ready for generation.
        All downstream stages are LOCKED.
        """
        artifacts = []
        stage_types = await self._stage_types(project.id)
        for artifact_type in stage_types:
            artifact = Artifact(
                project_id=project.id,
                client_id=project.client_id,
                artifact_type=artifact_type,
                current_version=0,
                gate_status=GateStatus.LOCKED,
            )
            self.db.add(artifact)
            artifacts.append(artifact)

        await self.db.flush()
        return artifacts

    # ── Gate Enforcement ──────────────────────────────────────

    async def can_generate(self, project_id: str, artifact_type: str) -> bool:
        """Read eligibility using current, transitively valid approval gates.

        Querying eligibility never repairs persisted state or creates audit
        records. A stale stored approval cannot unlock its descendants.
        """
        with self.db.no_autoflush:
            stage_map = await self._stage_map(project_id)
            artifacts = await self._load_stage_artifacts(project_id)
        stage_name = self._stage_name(artifact_type)
        stage = stage_map.get(stage_name)
        artifact = artifacts.get(stage_name)
        if stage is None or artifact is None or artifact.gate_status == GateStatus.GENERATING:
            return False
        effective = self._effective_gate_statuses(stage_map, artifacts)
        return all(
            effective.get(dependency) == GateStatus.APPROVED
            for dependency in stage.get("depends_on", [])
        )

    async def assert_can_generate(self, project_id: str, artifact_type: str) -> None:
        """Raise WorkflowError if the stage cannot generate."""
        if not await self.can_generate(project_id, artifact_type):
            stage_name = self._stage_name(artifact_type)
            stage = (await self._stage_map(project_id)).get(stage_name, {})
            dep_names = stage.get("depends_on", [])
            raise WorkflowError(
                f"Cannot generate {stage_name}: "
                f"upstream dependencies {dep_names} must be APPROVED first."
            )

    async def get_approved_version(
        self, project_id: str, artifact_type: str
    ) -> ArtifactVersion | None:
        """Get the latest approved version of an artifact."""
        artifact = await self._get_artifact(project_id, artifact_type)
        if not artifact or artifact.gate_status != GateStatus.APPROVED:
            return None
        stage_map = await self._stage_map(project_id)
        if (
            self._effective_gate_statuses(
                stage_map, await self._load_stage_artifacts(project_id)
            ).get(self._stage_name(artifact_type))
            != GateStatus.APPROVED
        ):
            return None
        result = await self.db.execute(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.client_id == artifact.client_id,
                ArtifactVersion.state == VersionState.APPROVED,
                ArtifactVersion.version_number == artifact.current_version,
            )
            .order_by(ArtifactVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_approved_content(
        self, project_id: str, artifact_type: str
    ) -> dict[str, Any] | None:
        """Get the content of the latest approved version of an artifact."""
        v = await self.get_approved_version(project_id, artifact_type)
        return v.content if v else None

    # ── State Transitions ─────────────────────────────────────

    async def start_generation(self, project_id: str, artifact_type: str) -> Artifact:
        """Mark an artifact as GENERATING. Verifies gate enforcement."""
        from app.services.project_revisions import lock_project

        project = await self.db.get(Project, project_id)
        if project is None:
            raise WorkflowError("Project is unavailable")
        await lock_project(self.db, project)
        await self.assert_can_generate(project_id, artifact_type)

        artifact = await self._get_artifact(project_id, artifact_type)
        if artifact is None:
            raise WorkflowError(f"Artifact {artifact_type} not found for project.")

        artifact.gate_status = GateStatus.GENERATING
        project.last_activity_at = datetime.now(UTC)
        project.workflow_status = "GENERATING"
        await self.invalidate_downstream(project_id, artifact_type)
        await self.db.flush()
        return artifact

    async def complete_generation(
        self,
        artifact: Artifact,
        content: dict[str, Any],
        ai_model_version: str | None = None,
        input_context_snapshot: dict[str, Any] | None = None,
        generation_run_id: str | None = None,
    ) -> ArtifactVersion:
        """
        Create a new version after AI generation completes.

        The version starts in DRAFT state. The artifact gate moves to PENDING_REVIEW
        after automated validation passes (handled separately).
        """
        new_version_number = artifact.current_version + 1
        if input_context_snapshot is None:
            project = await self._require_project(artifact.project_id)
            inputs = await self.current_bindings(artifact.project_id, artifact.artifact_type)
            input_context_snapshot = {
                "input_bindings": inputs,
                "requirement": project.business_requirement,
                "schema_context": project.erp_schema_context,
            }

        # Find the previous version (for lineage)
        parent_version_id = None
        if artifact.current_version > 0:
            prev_version = await self._get_latest_version(artifact.id)
            if prev_version:
                parent_version_id = prev_version.id

        version = ArtifactVersion(
            artifact_id=artifact.id,
            client_id=artifact.client_id,
            version_number=new_version_number,
            state=VersionState.DRAFT,
            content=content,
            parent_version_id=parent_version_id,
            ai_model_version=ai_model_version,
            generation_run_id=generation_run_id,
            input_context_snapshot=input_context_snapshot,
        )
        self.db.add(version)

        artifact.current_version = new_version_number
        await self.db.flush()

        # Create audit entry
        await self._create_audit(
            version=version,
            project_id=artifact.project_id,
            action=AuditAction.CREATED,
            actor="ai",
            comments=f"Generated v{new_version_number} using {ai_model_version or 'unknown'}",
        )

        # Any new upstream revision makes existing downstream approvals stale,
        # even while this revision is awaiting human approval.
        await self.invalidate_downstream(artifact.project_id, artifact.artifact_type)

        return version

    async def mark_validated(self, version: ArtifactVersion) -> None:
        """
        Transition a version from DRAFT → AI_VALIDATED → PENDING_HUMAN_REVIEW.

        Also updates the artifact's gate status to PENDING_REVIEW.
        """
        if version.state not in (VersionState.DRAFT,):
            raise WorkflowError(
                f"Cannot validate version in state {version.state}. Expected DRAFT."
            )

        version.state = VersionState.AI_VALIDATED
        await self.db.flush()

        await self._create_audit(
            version=version,
            project_id=(await self._get_artifact_by_id(version.artifact_id)).project_id,
            action=AuditAction.VALIDATED,
            actor="system",
            comments="Automated validation completed",
        )

        # Immediately submit for review
        version.state = VersionState.PENDING_HUMAN_REVIEW
        artifact = await self._get_artifact_by_id(version.artifact_id)
        project = await self._require_project(artifact.project_id)
        project.workflow_status = "PENDING_REVIEW"
        project.last_activity_at = datetime.now(UTC)
        artifact.gate_status = GateStatus.PENDING_REVIEW
        await self.db.flush()

        await self._create_audit(
            version=version,
            project_id=artifact.project_id,
            action=AuditAction.SUBMITTED_FOR_REVIEW,
            actor="system",
            comments="Submitted for human review",
        )

    async def approve(
        self, version: ArtifactVersion, reviewer: str, comments: str | None = None
    ) -> None:
        """
        Human approves a version. Transitions to APPROVED state.

        Rule: Only PENDING_HUMAN_REVIEW versions can be approved.
        """
        if version.state != VersionState.PENDING_HUMAN_REVIEW:
            raise WorkflowError(
                f"Cannot approve version in state {version.state}. Expected PENDING_HUMAN_REVIEW."
            )

        artifact = await self._get_artifact_by_id(version.artifact_id)
        if version.version_number != artifact.current_version:
            raise WorkflowError("Only the current artifact revision can be approved.")
        if artifact.gate_status != GateStatus.PENDING_REVIEW:
            raise WorkflowError("This revision is no longer eligible for active approval.")
        captured = (version.input_context_snapshot or {}).get("input_bindings")
        if captured is not None and captured != await self.current_bindings(
            artifact.project_id, artifact.artifact_type
        ):
            raise WorkflowError("The inputs changed; generate a new revision before approval.")
        if self.review_blockers(version.content):
            raise WorkflowError("Resolve blocking requirement questions before approval.")
        stage = (await self._stage_map(artifact.project_id)).get(
            self._stage_name(artifact.artifact_type)
        )
        dependencies = stage.get("depends_on", []) if stage else []
        for dependency in dependencies:
            upstream = await self._get_artifact(artifact.project_id, dependency)
            if upstream is None or upstream.gate_status != GateStatus.APPROVED:
                raise WorkflowError(
                    f"Cannot approve {artifact.artifact_type}: "
                    f"upstream stage {dependency} must be APPROVED first."
                )
        version.state = VersionState.APPROVED
        version.reviewer = reviewer
        version.reviewed_at = datetime.now(UTC)
        version.review_comments = comments
        artifact.gate_status = GateStatus.APPROVED
        project = await self._require_project(artifact.project_id)
        stages = await self.get_workflow_status(project)
        project.workflow_status = (
            "READY_FOR_SANDBOX"
            if all(item["gate_status"] == "APPROVED" for item in stages["stages"])
            else "IN_PROGRESS"
        )
        project.last_activity_at = datetime.now(UTC)
        await self.db.flush()

        await self._create_audit(
            version=version,
            project_id=artifact.project_id,
            action=AuditAction.APPROVED,
            actor=f"human:{reviewer}",
            comments=comments,
        )

    async def request_changes(self, version: ArtifactVersion, reviewer: str, comments: str) -> None:
        """
        Human requests changes. The current version is marked REQUEST_CHANGES.

        A new generation cycle must be triggered to create a new version.
        """
        if version.state != VersionState.PENDING_HUMAN_REVIEW:
            raise WorkflowError(
                f"Cannot request changes on version in state {version.state}. "
                f"Expected PENDING_HUMAN_REVIEW."
            )

        artifact = await self._get_artifact_by_id(version.artifact_id)
        if version.version_number != artifact.current_version:
            raise WorkflowError("Only the current artifact revision can be sent back for changes.")
        if artifact.gate_status != GateStatus.PENDING_REVIEW:
            raise WorkflowError("This revision is no longer eligible for review.")

        version.state = VersionState.REQUEST_CHANGES
        version.reviewer = reviewer
        version.reviewed_at = datetime.now(UTC)
        version.review_comments = comments

        # Artifact gate goes back to LOCKED, awaiting regeneration
        artifact.gate_status = GateStatus.LOCKED
        project = await self._require_project(artifact.project_id)
        project.workflow_status = "CHANGES_REQUESTED"
        project.last_activity_at = datetime.now(UTC)
        await self.invalidate_downstream(artifact.project_id, artifact.artifact_type)
        await self.db.flush()

        await self._create_audit(
            version=version,
            project_id=artifact.project_id,
            action=AuditAction.CHANGES_REQUESTED,
            actor=f"human:{reviewer}",
            comments=comments,
        )

    async def reject(
        self, version: ArtifactVersion, reviewer: str, comments: str | None = None
    ) -> None:
        """Human rejects a version outright."""
        if version.state != VersionState.PENDING_HUMAN_REVIEW:
            raise WorkflowError(
                f"Cannot reject version in state {version.state}. Expected PENDING_HUMAN_REVIEW."
            )

        artifact = await self._get_artifact_by_id(version.artifact_id)
        if version.version_number != artifact.current_version:
            raise WorkflowError("Only the current artifact revision can be rejected.")
        if artifact.gate_status != GateStatus.PENDING_REVIEW:
            raise WorkflowError("This revision is no longer eligible for review.")

        version.state = VersionState.REJECTED
        version.reviewer = reviewer
        version.reviewed_at = datetime.now(UTC)
        version.review_comments = comments

        artifact.gate_status = GateStatus.LOCKED
        project = await self._require_project(artifact.project_id)
        project.workflow_status = "CHANGES_REQUESTED"
        project.last_activity_at = datetime.now(UTC)
        await self.invalidate_downstream(artifact.project_id, artifact.artifact_type)
        await self.db.flush()

        await self._create_audit(
            version=version,
            project_id=artifact.project_id,
            action=AuditAction.REJECTED,
            actor=f"human:{reviewer}",
            comments=comments,
        )

    # ── Dependency Invalidation ───────────────────────────────

    async def invalidate_downstream(self, project_id: str, changed_artifact_type: str) -> list[str]:
        """
        When an approved artifact changes, invalidate all downstream
        artifacts that depend on it (directly or transitively).

        Returns the list of artifact types that were invalidated.
        """
        invalidated: list[str] = []
        stages = await self._stage_map(project_id)
        changed_name = self._stage_name(changed_artifact_type)
        affected = {changed_name}
        while True:
            newly_affected = {
                stage_type
                for stage_type, config in stages.items()
                if stage_type not in affected
                and any(dep in affected for dep in config.get("depends_on", []))
            }
            if not newly_affected:
                break
            affected.update(newly_affected)

        for downstream_type in [s for s in stages if s in affected and s != changed_name]:
            artifact = await self._get_artifact(project_id, downstream_type)
            if artifact is None:
                continue

            if artifact.gate_status != GateStatus.LOCKED:
                artifact.gate_status = GateStatus.INVALIDATED
                invalidated.append(downstream_type)

                # Mark latest version as invalidated
                latest = await self._get_latest_version(artifact.id)
                if latest and latest.state in (
                    VersionState.APPROVED,
                    VersionState.PENDING_HUMAN_REVIEW,
                ):
                    await self._create_audit(
                        version=latest,
                        project_id=project_id,
                        action=AuditAction.INVALIDATED,
                        actor="system",
                        comments=(f"Invalidated because upstream {changed_name} changed"),
                    )

        from app.services.project_revisions import stale_jobs

        await stale_jobs(self.db, project_id, affected - {changed_name})
        await self.db.flush()
        return invalidated

    async def invalidate_all(self, project_id: str) -> None:
        """Invalidate applicability, preserving historical approval decisions and bytes."""
        from app.services.project_revisions import stale_jobs

        artifacts = await self._load_stage_artifacts(project_id)
        for artifact in artifacts.values():
            artifact.gate_status = (
                GateStatus.INVALIDATED if artifact.current_version else GateStatus.LOCKED
            )
            latest = await self._get_latest_version(artifact.id)
            if latest:
                await self._create_audit(
                    latest,
                    project_id,
                    AuditAction.INVALIDATED,
                    "system",
                    "Project inputs changed; historical decision preserved.",
                )
        await stale_jobs(self.db, project_id, set(artifacts))
        await self.db.flush()

    async def current_bindings(self, project_id: str, stage_name: str) -> dict:
        project = await self._require_project(project_id)
        stages = await self._stage_map(project_id)
        artifacts = await self._load_stage_artifacts(project_id)
        dependencies: set[str] = set()
        pending = list(stages.get(stage_name, {}).get("depends_on", []))
        while pending:
            dependency = pending.pop()
            if dependency in dependencies:
                continue
            dependencies.add(dependency)
            pending.extend(stages.get(dependency, {}).get("depends_on", []))
        upstream = {}
        for name in sorted(dependencies):
            item = artifacts.get(name)
            version = await self.get_approved_version(project_id, name) if item else None
            upstream[name] = version.id if version else None
        return {
            "profile_version_id": project.erp_profile_version_id,
            "requirement_version": project.requirement_version,
            "schema_context_version": project.schema_context_version,
            "upstream_artifacts": upstream,
            **(await self._pattern_bindings(project)),
        }

    async def _pattern_bindings(self, project):
        from app.services.integration_patterns import pattern_bindings

        return await pattern_bindings(self.db, project)

    # ── Workflow Status ───────────────────────────────────────

    async def get_workflow_status(self, project: Project) -> dict[str, Any]:
        """Return a derived workflow view without modifying records.

        Historical inconsistent gates are shown as INVALIDATED when an
        upstream approval is no longer valid. Repairing those rows is a
        separate, explicit command; a GET must never perform reconciliation.
        """
        with self.db.no_autoflush:
            stage_map = await self._stage_map(project.id)
            artifacts = await self._load_stage_artifacts(project.id)
        effective = self._effective_gate_statuses(stage_map, artifacts)
        current_contents: dict[str, dict[str, Any]] = dict(
            (
                await self.db.execute(
                    select(ArtifactVersion.artifact_id, ArtifactVersion.content)
                    .join(Artifact)
                    .where(
                        Artifact.project_id == project.id,
                        ArtifactVersion.client_id.is_not_distinct_from(project.client_id),
                        ArtifactVersion.version_number == Artifact.current_version,
                    )
                )
            ).all()
        )
        stages = []
        current_stage = None
        for stage_name, config in stage_map.items():
            artifact = artifacts.get(stage_name)
            gate_status = effective.get(stage_name, GateStatus.LOCKED)
            can_generate = (
                artifact is not None
                and artifact.gate_status != GateStatus.GENERATING
                and all(
                    effective.get(dependency) == GateStatus.APPROVED
                    for dependency in config.get("depends_on", [])
                )
            )
            stages.append(
                {
                    "stage": stage_name,
                    "gate_status": gate_status.value,
                    "current_version": artifact.current_version if artifact else 0,
                    "artifact_id": artifact.id if artifact else None,
                    "label": config.get("label"),
                    "depends_on": config.get("depends_on", []),
                    "review_role": self.configured_review_role(stage_name, config),
                    "can_generate": can_generate,
                    "approval_blockers": self.review_blockers(
                        current_contents.get(artifact.id, {}) if artifact else {}
                    ),
                }
            )
            if current_stage is None and artifact is not None:
                if gate_status in (
                    GateStatus.GENERATING,
                    GateStatus.PENDING_REVIEW,
                    GateStatus.INVALIDATED,
                ) or (gate_status == GateStatus.LOCKED and can_generate):
                    current_stage = stage_name
        return {
            "project_id": project.id,
            "project_name": project.name,
            "current_stage": current_stage,
            "stages": stages,
        }

    async def _load_stage_artifacts(self, project_id: str) -> dict[str, Artifact]:
        result = await self.db.execute(
            select(Artifact)
            .join(Project)
            .where(
                Artifact.project_id == project_id,
                Artifact.client_id.is_not_distinct_from(Project.client_id),
            )
        )
        return {self._stage_name(artifact.artifact_type): artifact for artifact in result.scalars()}

    @staticmethod
    def _effective_gate_statuses(
        stage_map: dict[str, dict[str, Any]], artifacts: dict[str, Artifact]
    ) -> dict[str, GateStatus]:
        """Derive transitive gate validity, blocking missing or cyclic dependencies."""
        effective: dict[str, GateStatus] = {}
        active = {GateStatus.APPROVED, GateStatus.PENDING_REVIEW, GateStatus.GENERATING}

        def resolve(stage_name: str, visiting: frozenset[str]) -> GateStatus:
            if stage_name in effective:
                return effective[stage_name]
            if stage_name in visiting:
                return GateStatus.INVALIDATED
            artifact = artifacts.get(stage_name)
            if artifact is None or stage_name not in stage_map:
                return GateStatus.LOCKED
            gate = artifact.gate_status
            dependencies_valid = all(
                resolve(dependency, visiting | {stage_name}) == GateStatus.APPROVED
                for dependency in stage_map[stage_name].get("depends_on", [])
            )
            effective[stage_name] = (
                GateStatus.INVALIDATED if gate in active and not dependencies_valid else gate
            )
            return effective[stage_name]

        for stage_name in stage_map:
            resolve(stage_name, frozenset())
        return effective

    async def reconcile_gate_consistency(
        self, project_id: str, stage_map: dict[str, dict[str, Any]] | None = None
    ) -> None:
        """Explicit repair command; callers must authorize and commit its audited changes.

        This command is intentionally never invoked by a read/status operation.
        """
        stages = stage_map if stage_map is not None else await self._stage_map(project_id)
        for stage_name, config in stages.items():
            dependencies = config.get("depends_on", [])
            if not dependencies:
                continue
            dependency_artifacts = [
                await self._get_artifact(project_id, dep) for dep in dependencies
            ]
            if all(
                item is not None and item.gate_status == GateStatus.APPROVED
                for item in dependency_artifacts
            ):
                continue
            artifact = await self._get_artifact(project_id, stage_name)
            if artifact is None or artifact.gate_status not in (
                GateStatus.APPROVED,
                GateStatus.PENDING_REVIEW,
            ):
                continue
            artifact.gate_status = GateStatus.INVALIDATED
            latest = await self._get_latest_version(artifact.id)
            if latest and latest.state in (
                VersionState.APPROVED,
                VersionState.PENDING_HUMAN_REVIEW,
            ):
                await self._create_audit(
                    version=latest,
                    project_id=project_id,
                    action=AuditAction.INVALIDATED,
                    actor="system",
                    comments=(
                        "Invalidated because configured upstream stage(s) "
                        f"for {stage_name} are not approved."
                    ),
                )
        await self.db.flush()

    # ── Private Helpers ───────────────────────────────────────

    async def _get_artifact(self, project_id: str, artifact_type: str) -> Artifact | None:
        """Get an artifact by project and type."""
        result = await self.db.execute(
            select(Artifact)
            .join(Project)
            .where(
                Artifact.project_id == project_id,
                Artifact.client_id.is_not_distinct_from(Project.client_id),
                Artifact.artifact_type == self._stage_name(artifact_type),
            )
        )
        return result.scalar_one_or_none()

    async def _get_artifact_by_id(self, artifact_id: str) -> Artifact:
        """Get an artifact by its ID."""
        result = await self.db.execute(select(Artifact).where(Artifact.id == artifact_id))
        artifact = result.scalar_one_or_none()
        if artifact is None:
            raise WorkflowError(f"Artifact {artifact_id} not found")
        return artifact

    async def _get_latest_version(self, artifact_id: str) -> ArtifactVersion | None:
        """Get the most recent version of an artifact."""
        result = await self.db.execute(
            select(ArtifactVersion)
            .join(Artifact)
            .where(
                ArtifactVersion.artifact_id == artifact_id,
                ArtifactVersion.client_id.is_not_distinct_from(Artifact.client_id),
            )
            .order_by(ArtifactVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _create_audit(
        self,
        version: ArtifactVersion,
        project_id: str,
        action: AuditAction,
        actor: str,
        comments: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Create an audit trail entry."""
        entry = AuditEntry(
            artifact_version_id=version.id,
            project_id=project_id,
            client_id=version.client_id,
            actor_subject_id=self.actor_subject_id,
            action=action,
            actor=actor,
            comments=comments,
            metadata_=metadata,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def _require_project(self, project_id: str) -> Project:
        project = await self.db.get(Project, project_id)
        if project is None:
            raise WorkflowError("Project is unavailable")
        return project

    async def _stage_map(self, project_id: str) -> dict[str, dict[str, Any]]:
        project = await self.db.get(Project, project_id)
        if project and project.erp_profile_version_id:
            version = await self.db.get(ERPProfileVersion, project.erp_profile_version_id)
            if version:
                return self.configured_stage_map(version.configuration)
        return {}

    async def _stage_types(self, project_id: str) -> list[str]:
        return list((await self._stage_map(project_id)).keys())
