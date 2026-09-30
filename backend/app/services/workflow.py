"""
erpFusion — Workflow Engine

Orchestrates the artifact generation pipeline with strict gate enforcement.

Key responsibilities:
  1. Enforce stage ordering (no stage may proceed until upstream is APPROVED).
  2. Manage artifact state transitions (DRAFT → AI_VALIDATED → PENDING_REVIEW → APPROVED).
  3. Cascade dependency invalidation when upstream artifacts change.
  4. Create audit entries for every lifecycle event.

The workflow defines this dependency chain:
  CONTEXT_ANALYSIS → FDD → TDD → SQL → PKS_PKB → DEPLOYMENT
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Artifact,
    ArtifactVersion,
    AuditAction,
    AuditEntry,
    GateStatus,
    Project,
    ERPProfileVersion,
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

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _stage_name(artifact_type) -> str:
        """Normalize legacy enum values and data-defined stage strings."""
        return artifact_type.value if isinstance(artifact_type, Enum) else str(artifact_type)

    @staticmethod
    def configured_stage_map(configuration: dict) -> dict[str, dict]:
        """Return configured stages with their declared dependencies plus strict sequence order."""
        stage_list = configuration.get("workflow", {}).get("stages", [])
        result: dict[str, dict] = {}
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
        """
        Check whether a stage is eligible for generation.

        A stage can generate only if ALL upstream dependencies are APPROVED.
        """
        stage_name = self._stage_name(artifact_type)
        stage_map = await self._stage_map(project_id)
        stage = stage_map.get(stage_name)
        if stage is None:
            return False
        dependencies = stage.get("depends_on", [])

        for dep_type in dependencies:
            dep_artifact = await self._get_artifact(project_id, dep_type)
            if dep_artifact is None or dep_artifact.gate_status != GateStatus.APPROVED:
                return False

        return True

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
        if not artifact:
            return None
        result = await self.db.execute(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.artifact_id == artifact.id,
                ArtifactVersion.state == VersionState.APPROVED,
            )
            .order_by(ArtifactVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_approved_content(
        self, project_id: str, artifact_type: str
    ) -> dict | None:
        """Get the content of the latest approved version of an artifact."""
        v = await self.get_approved_version(project_id, artifact_type)
        return v.content if v else None

    # ── State Transitions ─────────────────────────────────────

    async def start_generation(
        self, project_id: str, artifact_type: str
    ) -> Artifact:
        """Mark an artifact as GENERATING. Verifies gate enforcement."""
        await self.assert_can_generate(project_id, artifact_type)

        artifact = await self._get_artifact(project_id, artifact_type)
        if artifact is None:
            raise WorkflowError(f"Artifact {artifact_type} not found for project.")

        artifact.gate_status = GateStatus.GENERATING
        await self.db.flush()
        return artifact

    async def complete_generation(
        self,
        artifact: Artifact,
        content: dict,
        ai_model_version: str | None = None,
        input_context_snapshot: dict | None = None,
        generation_run_id: str | None = None,
    ) -> ArtifactVersion:
        """
        Create a new version after AI generation completes.

        The version starts in DRAFT state. The artifact gate moves to PENDING_REVIEW
        after automated validation passes (handled separately).
        """
        new_version_number = artifact.current_version + 1

        # Find the previous version (for lineage)
        parent_version_id = None
        if artifact.current_version > 0:
            prev_version = await self._get_latest_version(artifact.id)
            if prev_version:
                parent_version_id = prev_version.id

        version = ArtifactVersion(
            artifact_id=artifact.id,
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
                f"Cannot approve version in state {version.state}. "
                f"Expected PENDING_HUMAN_REVIEW."
            )

        artifact = await self._get_artifact_by_id(version.artifact_id)
        if version.version_number != artifact.current_version:
            raise WorkflowError("Only the current artifact revision can be approved.")
        stage = (await self._stage_map(artifact.project_id)).get(self._stage_name(artifact.artifact_type))
        dependencies = stage.get("depends_on", []) if stage else []
        for dependency in dependencies:
            upstream = await self._get_artifact(artifact.project_id, dependency)
            if upstream is None or upstream.gate_status != GateStatus.APPROVED:
                raise WorkflowError(
                    f"Cannot approve {artifact.artifact_type}: upstream stage {dependency} must be APPROVED first."
                )
        version.state = VersionState.APPROVED
        version.reviewer = reviewer
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_comments = comments
        artifact.gate_status = GateStatus.APPROVED
        await self.db.flush()

        await self._create_audit(
            version=version,
            project_id=artifact.project_id,
            action=AuditAction.APPROVED,
            actor=f"human:{reviewer}",
            comments=comments,
        )

    async def request_changes(
        self, version: ArtifactVersion, reviewer: str, comments: str
    ) -> None:
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

        version.state = VersionState.REQUEST_CHANGES
        version.reviewer = reviewer
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_comments = comments

        # Artifact gate goes back to LOCKED, awaiting regeneration
        artifact.gate_status = GateStatus.LOCKED
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
                f"Cannot reject version in state {version.state}. "
                f"Expected PENDING_HUMAN_REVIEW."
            )

        artifact = await self._get_artifact_by_id(version.artifact_id)
        if version.version_number != artifact.current_version:
            raise WorkflowError("Only the current artifact revision can be rejected.")

        version.state = VersionState.REJECTED
        version.reviewer = reviewer
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_comments = comments

        artifact.gate_status = GateStatus.LOCKED
        await self.db.flush()

        await self._create_audit(
            version=version,
            project_id=artifact.project_id,
            action=AuditAction.REJECTED,
            actor=f"human:{reviewer}",
            comments=comments,
        )

    # ── Dependency Invalidation ───────────────────────────────

    async def invalidate_downstream(
        self, project_id: str, changed_artifact_type: str
    ) -> list[str]:
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
                stage_type for stage_type, config in stages.items()
                if stage_type not in affected and any(dep in affected for dep in config.get("depends_on", []))
            }
            if not newly_affected:
                break
            affected.update(newly_affected)

        for downstream_type in [s for s in stages if s in affected and s != changed_name]:
            artifact = await self._get_artifact(project_id, downstream_type)
            if artifact is None:
                continue

            if artifact.gate_status in (GateStatus.APPROVED, GateStatus.PENDING_REVIEW):
                artifact.gate_status = GateStatus.INVALIDATED
                invalidated.append(downstream_type)

                # Mark latest version as invalidated
                latest = await self._get_latest_version(artifact.id)
                if latest and latest.state in (
                    VersionState.APPROVED,
                    VersionState.PENDING_HUMAN_REVIEW,
                ):
                    latest.state = VersionState.INVALIDATED
                    await self._create_audit(
                        version=latest,
                        project_id=project_id,
                        action=AuditAction.INVALIDATED,
                        actor="system",
                        comments=(
                            f"Invalidated because upstream {changed_name} changed"
                        ),
                    )

        await self.db.flush()
        return invalidated

    # ── Workflow Status ───────────────────────────────────────

    async def get_workflow_status(self, project: Project) -> dict:
        """
        Get the full workflow status for a project, showing each stage's
        gate status and determining the current active stage.
        """
        stages = []
        current_stage = None
        stage_map = await self._stage_map(project.id)
        await self.reconcile_gate_consistency(project.id, stage_map)

        for artifact_type in await self._stage_types(project.id):
            artifact = await self._get_artifact(project.id, artifact_type)

            stage_info = {
                "stage": str(artifact_type),
                "gate_status": artifact.gate_status.value if artifact else GateStatus.LOCKED.value,
                "current_version": artifact.current_version if artifact else 0,
                "artifact_id": artifact.id if artifact else None,
                "label": stage_map.get(str(artifact_type), {}).get("label"),
                "depends_on": stage_map.get(str(artifact_type), {}).get("depends_on", []),
                "can_generate": await self.can_generate(project.id, artifact_type),
            }
            stages.append(stage_info)

            # Determine current stage (first non-approved, non-locked stage, or first locked)
            if current_stage is None and artifact:
                if artifact.gate_status in (
                    GateStatus.GENERATING,
                    GateStatus.PENDING_REVIEW,
                    GateStatus.INVALIDATED,
                ):
                    current_stage = str(artifact_type)
                elif artifact.gate_status == GateStatus.LOCKED:
                    # Check if this is the next stage to work on
                    can_gen = await self.can_generate(project.id, artifact_type)
                    if can_gen:
                        current_stage = str(artifact_type)

        return {
            "project_id": project.id,
            "project_name": project.name,
            "current_stage": current_stage,
            "stages": stages,
        }

    async def reconcile_gate_consistency(self, project_id: str, stage_map: dict[str, dict] | None = None) -> None:
        """Invalidate stale downstream gates whose configured prerequisites are not approved."""
        stages = stage_map if stage_map is not None else await self._stage_map(project_id)
        for stage_name, config in stages.items():
            dependencies = config.get("depends_on", [])
            if not dependencies:
                continue
            dependency_artifacts = [await self._get_artifact(project_id, dep) for dep in dependencies]
            if all(item is not None and item.gate_status == GateStatus.APPROVED for item in dependency_artifacts):
                continue
            artifact = await self._get_artifact(project_id, stage_name)
            if artifact is None or artifact.gate_status not in (GateStatus.APPROVED, GateStatus.PENDING_REVIEW):
                continue
            artifact.gate_status = GateStatus.INVALIDATED
            latest = await self._get_latest_version(artifact.id)
            if latest and latest.state in (VersionState.APPROVED, VersionState.PENDING_HUMAN_REVIEW):
                latest.state = VersionState.INVALIDATED
                await self._create_audit(
                    version=latest,
                    project_id=project_id,
                    action=AuditAction.INVALIDATED,
                    actor="system",
                    comments=f"Invalidated because configured upstream stage(s) for {stage_name} are not approved.",
                )
        await self.db.flush()

    # ── Private Helpers ───────────────────────────────────────

    async def _get_artifact(
        self, project_id: str, artifact_type: str
    ) -> Artifact | None:
        """Get an artifact by project and type."""
        result = await self.db.execute(
            select(Artifact).where(
                Artifact.project_id == project_id,
                Artifact.artifact_type == self._stage_name(artifact_type),
            )
        )
        return result.scalar_one_or_none()

    async def _get_artifact_by_id(self, artifact_id: str) -> Artifact:
        """Get an artifact by its ID."""
        result = await self.db.execute(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        artifact = result.scalar_one_or_none()
        if artifact is None:
            raise WorkflowError(f"Artifact {artifact_id} not found")
        return artifact

    async def _get_latest_version(self, artifact_id: str) -> ArtifactVersion | None:
        """Get the most recent version of an artifact."""
        result = await self.db.execute(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id == artifact_id)
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
        metadata: dict | None = None,
    ) -> AuditEntry:
        """Create an audit trail entry."""
        entry = AuditEntry(
            artifact_version_id=version.id,
            project_id=project_id,
            action=action,
            actor=actor,
            comments=comments,
            metadata_=metadata,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def _stage_map(self, project_id: str) -> dict[str, dict]:
        project = await self.db.get(Project, project_id)
        if project and project.erp_profile_version_id:
            version = await self.db.get(ERPProfileVersion, project.erp_profile_version_id)
            if version:
                return self.configured_stage_map(version.configuration)
        return {}

    async def _stage_types(self, project_id: str) -> list[str]:
        return list((await self._stage_map(project_id)).keys())
