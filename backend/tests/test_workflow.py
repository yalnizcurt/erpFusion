"""
erpFusion — Workflow Engine Unit Tests

Tests the core workflow logic: gate enforcement, state transitions,
dependency invalidation, and audit trail creation.

Uses SQLite in-memory for fast testing (no PostgreSQL required).
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Artifact,
    ArtifactType,
    ArtifactVersion,
    AuditEntry,
    Base,
    ERPProfile,
    ERPProfileVersion,
    GateStatus,
    Project,
    ProjectStatus,
    VersionState,
)
from app.services.workflow import WorkflowEngine, WorkflowError

TEST_STAGE_TYPES = ["CONTEXT_ANALYSIS", "FDD", "TDD", "SQL", "PKS", "PKB", "DEPLOYMENT"]
TEST_STAGE_CONFIG = [
    {"type": "CONTEXT_ANALYSIS", "depends_on": []},
    {"type": "FDD", "depends_on": ["CONTEXT_ANALYSIS"]},
    {"type": "TDD", "depends_on": ["FDD"]},
    {"type": "SQL", "depends_on": ["TDD"]},
    {"type": "PKS", "depends_on": ["SQL"]},
    {"type": "PKB", "depends_on": ["SQL"]},
    {"type": "DEPLOYMENT", "depends_on": ["PKS", "PKB"]},
]


# ── Test Fixtures ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> Project:
    """Create a test project with initialized artifacts."""
    profile = ERPProfile(key="test-profile", name="Test ERP", display_name="Test ERP", vendor="Test", active=True)
    db_session.add(profile)
    await db_session.flush()
    profile_version = ERPProfileVersion(
        profile_id=profile.id, version=1, status="PUBLISHED", supported_artifact_types=TEST_STAGE_TYPES,
        configuration={"workflow": {"stages": TEST_STAGE_CONFIG}},
    )
    db_session.add(profile_version)
    await db_session.flush()
    proj = Project(
        name="Test Customer Extraction",
        description="Test project",
        business_requirement="Extract all active customer records...",
        erp_schema_context={
            "entities": [
                {
                    "table": "HZ_PARTIES",
                    "columns": [
                        {"name": "PARTY_ID", "type": "NUMBER", "pk": True},
                        {"name": "PARTY_NAME", "type": "VARCHAR2(360)"},
                    ],
                }
            ]
        },
        erp_profile_id=profile.id,
        erp_profile_version_id=profile_version.id,
        status=ProjectStatus.ACTIVE,
    )
    db_session.add(proj)
    await db_session.flush()

    workflow = WorkflowEngine(db_session)
    await workflow.initialize_project_artifacts(proj)
    await db_session.flush()

    return proj


# ══════════════════════════════════════════════════════════════
# Test: Project Initialization
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_initialize_creates_all_artifacts(project: Project, db_session: AsyncSession):
    """All artifact types should be created in LOCKED state."""
    result = await db_session.execute(
        select(Artifact).where(Artifact.project_id == project.id)
    )
    artifacts = list(result.scalars().all())
    assert len(artifacts) == len(TEST_STAGE_TYPES)

    for artifact in artifacts:
        assert artifact.gate_status == GateStatus.LOCKED
        assert artifact.current_version == 0


# ══════════════════════════════════════════════════════════════
# Test: Gate Enforcement
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_context_analysis_can_generate_without_dependencies(
    project: Project, db_session: AsyncSession
):
    """CONTEXT_ANALYSIS has no dependencies — should always be allowed."""
    workflow = WorkflowEngine(db_session)
    can = await workflow.can_generate(project.id, ArtifactType.CONTEXT_ANALYSIS)
    assert can is True


@pytest.mark.asyncio
async def test_fdd_cannot_generate_before_context_approved(
    project: Project, db_session: AsyncSession
):
    """FDD depends on CONTEXT_ANALYSIS — should be blocked when not approved."""
    workflow = WorkflowEngine(db_session)
    can = await workflow.can_generate(project.id, ArtifactType.FDD)
    assert can is False


@pytest.mark.asyncio
async def test_profile_stage_order_is_serial_even_when_declared_dependencies_branch(
    project: Project, db_session: AsyncSession
):
    workflow = WorkflowEngine(db_session)
    sql = await workflow._get_artifact(project.id, "SQL")
    sql.gate_status = GateStatus.APPROVED

    # PKB declares SQL as a dependency, but PKS appears immediately before it
    # in the configured stage order and must be approved first as well.
    assert await workflow.can_generate(project.id, "PKB") is False
    resolved = await workflow._stage_map(project.id)
    assert resolved["PKB"]["depends_on"] == ["PKS", "SQL"]


@pytest.mark.asyncio
async def test_fdd_can_generate_after_context_approved(
    project: Project, db_session: AsyncSession
):
    """FDD should be allowed after CONTEXT_ANALYSIS is approved."""
    workflow = WorkflowEngine(db_session)

    # Generate and approve context analysis
    artifact = await workflow.start_generation(project.id, ArtifactType.CONTEXT_ANALYSIS)
    version = await workflow.complete_generation(artifact, {"test": "content"}, "test-model")
    await workflow.mark_validated(version)
    await workflow.approve(version, "tester")
    await db_session.flush()

    # Now FDD should be allowed
    can = await workflow.can_generate(project.id, ArtifactType.FDD)
    assert can is True


@pytest.mark.asyncio
async def test_cannot_skip_stages(project: Project, db_session: AsyncSession):
    """SQL cannot be generated if TDD is not approved (even if FDD is)."""
    workflow = WorkflowEngine(db_session)

    with pytest.raises(WorkflowError, match="upstream dependencies"):
        await workflow.start_generation(project.id, ArtifactType.SQL)


# ══════════════════════════════════════════════════════════════
# Test: State Transitions
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_state_transition_flow(project: Project, db_session: AsyncSession):
    """Test: DRAFT → AI_VALIDATED → PENDING_HUMAN_REVIEW → APPROVED."""
    workflow = WorkflowEngine(db_session)

    # Start generation
    artifact = await workflow.start_generation(project.id, ArtifactType.CONTEXT_ANALYSIS)
    assert artifact.gate_status == GateStatus.GENERATING

    # Complete generation
    version = await workflow.complete_generation(
        artifact, {"analysis": "test"}, "groq-test"
    )
    assert version.state == VersionState.DRAFT
    assert version.version_number == 1

    # Mark validated
    await workflow.mark_validated(version)
    assert version.state == VersionState.PENDING_HUMAN_REVIEW
    assert artifact.gate_status == GateStatus.PENDING_REVIEW

    # Approve
    await workflow.approve(version, "reviewer1", "Looks good")
    assert version.state == VersionState.APPROVED
    assert artifact.gate_status == GateStatus.APPROVED
    assert version.reviewer == "reviewer1"
    assert version.review_comments == "Looks good"


@pytest.mark.asyncio
async def test_request_changes_flow(project: Project, db_session: AsyncSession):
    """Test REQUEST_CHANGES creates opportunity for regeneration."""
    workflow = WorkflowEngine(db_session)

    artifact = await workflow.start_generation(project.id, ArtifactType.CONTEXT_ANALYSIS)
    version = await workflow.complete_generation(artifact, {"v1": True}, "test")
    await workflow.mark_validated(version)

    # Request changes
    await workflow.request_changes(version, "reviewer1", "Please fix the join logic")
    assert version.state == VersionState.REQUEST_CHANGES
    assert artifact.gate_status == GateStatus.LOCKED

    # Regenerate (new version)
    artifact.gate_status = GateStatus.GENERATING  # Simulate re-trigger
    v2 = await workflow.complete_generation(artifact, {"v2": True}, "test")
    assert v2.version_number == 2
    assert v2.parent_version_id == version.id


@pytest.mark.asyncio
async def test_reject_flow(project: Project, db_session: AsyncSession):
    """Test REJECTED state transition."""
    workflow = WorkflowEngine(db_session)

    artifact = await workflow.start_generation(project.id, ArtifactType.CONTEXT_ANALYSIS)
    version = await workflow.complete_generation(artifact, {"test": True}, "test")
    await workflow.mark_validated(version)

    await workflow.reject(version, "reviewer1", "Completely wrong analysis")
    assert version.state == VersionState.REJECTED
    assert artifact.gate_status == GateStatus.LOCKED


@pytest.mark.asyncio
async def test_cannot_approve_non_pending_version(project: Project, db_session: AsyncSession):
    """Cannot approve a version that is not PENDING_HUMAN_REVIEW."""
    workflow = WorkflowEngine(db_session)

    artifact = await workflow.start_generation(project.id, ArtifactType.CONTEXT_ANALYSIS)
    version = await workflow.complete_generation(artifact, {"test": True}, "test")
    # version is in DRAFT state, not PENDING_HUMAN_REVIEW

    with pytest.raises(WorkflowError, match="Expected PENDING_HUMAN_REVIEW"):
        await workflow.approve(version, "reviewer1")


# ══════════════════════════════════════════════════════════════
# Test: Dependency Invalidation
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_invalidate_downstream_on_upstream_change(
    project: Project, db_session: AsyncSession
):
    """When CONTEXT_ANALYSIS changes, all downstream should be invalidated."""
    workflow = WorkflowEngine(db_session)

    # Approve context analysis
    ctx = await workflow.start_generation(project.id, ArtifactType.CONTEXT_ANALYSIS)
    ctx_v = await workflow.complete_generation(ctx, {"ctx": True}, "test")
    await workflow.mark_validated(ctx_v)
    await workflow.approve(ctx_v, "reviewer")

    # Approve FDD
    fdd = await workflow.start_generation(project.id, ArtifactType.FDD)
    fdd_v = await workflow.complete_generation(fdd, {"fdd": True}, "test")
    await workflow.mark_validated(fdd_v)
    await workflow.approve(fdd_v, "reviewer")

    await db_session.flush()

    # Now invalidate from CONTEXT_ANALYSIS
    invalidated = await workflow.invalidate_downstream(
        project.id, ArtifactType.CONTEXT_ANALYSIS
    )

    assert ArtifactType.FDD in invalidated
    assert fdd.gate_status == GateStatus.INVALIDATED


@pytest.mark.asyncio
async def test_regenerating_upstream_invalidates_approved_downstream_automatically(
    project: Project, db_session: AsyncSession
):
    workflow = WorkflowEngine(db_session)

    context = await workflow.start_generation(project.id, "CONTEXT_ANALYSIS")
    context_v1 = await workflow.complete_generation(context, {"ctx": 1}, "test")
    await workflow.mark_validated(context_v1)
    await workflow.approve(context_v1, "reviewer")

    fdd = await workflow.start_generation(project.id, "FDD")
    fdd_v1 = await workflow.complete_generation(fdd, {"fdd": 1}, "test")
    await workflow.mark_validated(fdd_v1)
    await workflow.approve(fdd_v1, "reviewer")

    tdd = await workflow.start_generation(project.id, "TDD")
    tdd_v1 = await workflow.complete_generation(tdd, {"tdd": 1}, "test")
    await workflow.mark_validated(tdd_v1)
    await workflow.approve(tdd_v1, "reviewer")

    context_v2_artifact = await workflow.start_generation(project.id, "CONTEXT_ANALYSIS")
    context_v2 = await workflow.complete_generation(context_v2_artifact, {"ctx": 2}, "test")
    await workflow.mark_validated(context_v2)

    assert context_v2_artifact.gate_status == GateStatus.PENDING_REVIEW
    assert fdd.gate_status == GateStatus.INVALIDATED
    assert fdd_v1.state == VersionState.INVALIDATED
    assert tdd.gate_status == GateStatus.INVALIDATED
    assert tdd_v1.state == VersionState.INVALIDATED
    assert await workflow.can_generate(project.id, "FDD") is False


@pytest.mark.asyncio
async def test_status_reconciles_stale_approved_stages_behind_pending_prerequisite(
    project: Project, db_session: AsyncSession
):
    workflow = WorkflowEngine(db_session)
    context = await workflow._get_artifact(project.id, "CONTEXT_ANALYSIS")
    fdd = await workflow._get_artifact(project.id, "FDD")
    tdd = await workflow._get_artifact(project.id, "TDD")
    context.gate_status = GateStatus.PENDING_REVIEW
    fdd.gate_status = GateStatus.APPROVED
    tdd.gate_status = GateStatus.APPROVED

    status = await workflow.get_workflow_status(project)

    actual = {stage["stage"]: stage["gate_status"] for stage in status["stages"]}
    assert actual["CONTEXT_ANALYSIS"] == "PENDING_REVIEW"
    assert actual["FDD"] == "INVALIDATED"
    assert actual["TDD"] == "INVALIDATED"


@pytest.mark.asyncio
async def test_downstream_approval_is_blocked_until_prerequisite_is_approved(
    project: Project, db_session: AsyncSession
):
    workflow = WorkflowEngine(db_session)
    fdd = await workflow._get_artifact(project.id, "FDD")
    fdd.current_version = 1
    fdd.gate_status = GateStatus.PENDING_REVIEW
    fdd_version = ArtifactVersion(
        artifact_id=fdd.id, version_number=1, state=VersionState.PENDING_HUMAN_REVIEW,
        content={"fdd": True},
    )
    await db_session.flush()

    with pytest.raises(WorkflowError, match="upstream stage CONTEXT_ANALYSIS must be APPROVED"):
        await workflow.approve(fdd_version, "reviewer")

    assert fdd_version.state == VersionState.PENDING_HUMAN_REVIEW


# ══════════════════════════════════════════════════════════════
# Test: Audit Trail
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_audit_entries_created(project: Project, db_session: AsyncSession):
    """Every state transition should create an audit entry."""
    workflow = WorkflowEngine(db_session)

    artifact = await workflow.start_generation(project.id, ArtifactType.CONTEXT_ANALYSIS)
    version = await workflow.complete_generation(artifact, {"test": True}, "test")
    await workflow.mark_validated(version)
    await workflow.approve(version, "reviewer1", "LGTM")

    await db_session.flush()

    # Should have audit entries: CREATED, VALIDATED, SUBMITTED_FOR_REVIEW, APPROVED
    result = await db_session.execute(
        select(AuditEntry).where(AuditEntry.artifact_version_id == version.id)
    )
    audit_entries = list(result.scalars().all())
    actions = [e.action.value for e in audit_entries]

    assert "CREATED" in actions
    assert "VALIDATED" in actions
    assert "SUBMITTED_FOR_REVIEW" in actions
    assert "APPROVED" in actions


# ══════════════════════════════════════════════════════════════
# Test: Workflow Status
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_workflow_status(project: Project, db_session: AsyncSession):
    """Workflow status should show all stages with correct gate statuses."""
    workflow = WorkflowEngine(db_session)

    status = await workflow.get_workflow_status(project)

    assert status["project_id"] == project.id
    assert status["project_name"] == project.name
    assert len(status["stages"]) == len(TEST_STAGE_TYPES)

    # First stage should be identified as current (it's LOCKED but can generate)
    assert status["current_stage"] == "CONTEXT_ANALYSIS"

    # All stages should be LOCKED initially
    for stage in status["stages"]:
        assert stage["gate_status"] == "LOCKED"
