"""Explicit seed loader for the initial Oracle profile and its governed prompt data."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ERPProfile, ERPProfileVersion, PromptVersion


async def ensure_seed_profiles(db: AsyncSession) -> ERPProfile:
    """Load the checked-in Oracle profile fixture once; runtime services read only registry data."""
    result = await db.execute(select(ERPProfile).where(ERPProfile.key == "oracle-fusion-cloud"))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ERPProfile(
            key="oracle-fusion-cloud", name="Oracle Fusion Cloud", display_name="Oracle Fusion Cloud",
            vendor="Oracle", product_version="Cloud", description="Seed profile for the existing Oracle implementation.",
            active=True, status="PUBLISHED", created_by="seed", updated_by="seed",
            configuration={"dialect": "Oracle", "schema_grounding_required": True},
        )
        db.add(profile)
        await db.flush()

    version_result = await db.execute(select(ERPProfileVersion).where(
        ERPProfileVersion.profile_id == profile.id, ERPProfileVersion.version == 1))
    profile_version = version_result.scalar_one_or_none()
    if profile_version is None:
        stages = [
            ("CONTEXT_ANALYSIS", [], "oracle_context_analysis", "CONTEXT_ANALYSIS"),
            ("FDD", ["CONTEXT_ANALYSIS"], "oracle_fdd", "FDD"),
            ("TDD", ["FDD"], "oracle_tdd", "TDD"),
            ("SQL", ["TDD"], "oracle_sql", "SQL"),
            ("PKS", ["SQL"], "oracle_plsql", "CODE_GENERATION"),
            ("PKB", ["SQL"], "oracle_plsql", "CODE_GENERATION"),
            ("DEPLOYMENT", ["PKS", "PKB"], "oracle_deployment", "DEPLOYMENT"),
        ]
        workflow_stages = [
            {"type": t, "depends_on": d, "adapter": a, "prompt_stage": ps, "label": t.replace("_", " ")}
            for t, d, a, ps in stages
        ]
        profile_version = ERPProfileVersion(
            profile_id=profile.id, version=1, status="PUBLISHED",
            supported_artifact_types=[x[0] for x in stages],
            configuration={
                "workflow": {"stages": workflow_stages},
                "generation": {"strategy": "configured_adapters"},
                "validation": {"schema_conformity": True, "adapters": {"SQL": "oracle_sql", "PKS": "oracle_plsql", "PKB": "oracle_plsql"},
                               "cross_artifact_traceability": True,
                               "traceability_adapter": "oracle_attribute_lineage"},
            },
            created_by="seed", updated_by="seed",
        )
        db.add(profile_version)
        await db.flush()

    fixture_path = Path(__file__).resolve().parents[2] / "seed" / "oracle_fusion.prompts.json"
    prompt_data = json.loads(fixture_path.read_text())
    for stage, content in prompt_data.items():
        result = await db.execute(select(PromptVersion.id).where(
            PromptVersion.profile_version_id == profile_version.id,
            PromptVersion.name == f"{stage} instructions", PromptVersion.version == 1))
        if result.scalar_one_or_none() is None:
            db.add(PromptVersion(
                scope="STAGE", profile_version_id=profile_version.id, name=f"{stage} instructions",
                stage=stage, content=content, version=1, status="PUBLISHED", variables=[],
                created_by="seed", updated_by="seed",
            ))
    profile.status = "PUBLISHED"
    profile.active = True
    await db.flush()
    return profile
