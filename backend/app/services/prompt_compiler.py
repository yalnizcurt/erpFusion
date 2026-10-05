"""Resolve a pinned ERP profile into a grounded generation context and provenance record."""

import re
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ERPAssetVersion,
    ERPProfile,
    ERPProfileVersion,
    FeedbackGuidance,
    Project,
    PromptVersion,
)


@dataclass
class CompiledGenerationContext:
    system_prompt: str
    user_prompt: str
    provenance: dict
    profile_version: ERPProfileVersion
    integration_pattern: dict | None = None


class PromptConfigurationError(Exception):
    pass


def validate_prompt_template(content: str, variables: list[str]) -> None:
    placeholders = set(re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", content))
    undeclared = placeholders - set(variables)
    if undeclared:
        raise PromptConfigurationError(
            f"Undeclared prompt placeholders: {', '.join(sorted(undeclared))}."
        )
    unsupported = placeholders - {
        "erp_name",
        "erp_vendor",
        "erp_version",
        "profile_version",
        "project_name",
        "requirement",
        "stage",
        "current_task",
    }
    if unsupported:
        raise PromptConfigurationError(
            f"Unsupported prompt placeholders: {', '.join(sorted(unsupported))}."
        )


class PromptCompiler:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def compile(
        self, project: Project, stage: str, current_task: str, upstream: dict
    ) -> CompiledGenerationContext:
        from app.services.integration_patterns import pattern_context

        integration_pattern = await pattern_context(self.db, project)
        if not project.erp_profile_version_id:
            raise PromptConfigurationError(
                "This request has no pinned ERP profile version. "
                "Select a published ERP profile to continue."
            )
        profile = await self.db.get(ERPProfileVersion, project.erp_profile_version_id)
        if not profile:
            raise PromptConfigurationError("The request's pinned ERP profile version is missing.")

        stage_config = self._stage_config(profile, stage)
        prompt_stage = str(stage_config.get("prompt_stage", stage)).upper()
        erp_identity = await self.db.get(ERPProfile, profile.profile_id)
        prompts_result = await self.db.execute(
            select(PromptVersion)
            .where(
                PromptVersion.status == "PUBLISHED",
                or_(
                    PromptVersion.profile_version_id == profile.id,
                    PromptVersion.profile_version_id.is_(None),
                ),
                or_(
                    and_(
                        PromptVersion.scope == "GLOBAL",
                        PromptVersion.stage.in_(["*", prompt_stage]),
                    ),
                    and_(
                        PromptVersion.scope == "ERP", PromptVersion.stage.in_(["*", prompt_stage])
                    ),
                    and_(PromptVersion.scope == "STAGE", PromptVersion.stage == prompt_stage),
                ),
            )
            .order_by(PromptVersion.scope, PromptVersion.version)
        )
        prompts = list(prompts_result.scalars())
        latest_prompts: dict[tuple, PromptVersion] = {}
        for prompt in prompts:
            key = (prompt.scope, prompt.stage, prompt.name)
            if key not in latest_prompts or prompt.version > latest_prompts[key].version:
                latest_prompts[key] = prompt
        prompts = sorted(
            latest_prompts.values(),
            key=lambda prompt: (
                {"GLOBAL": 0, "ERP": 1, "STAGE": 2}.get(prompt.scope, 3),
                prompt.stage,
                prompt.name,
            ),
        )
        stage_prompts = [p for p in prompts if p.scope in {"ERP", "STAGE"}]
        if not stage_prompts:
            raise PromptConfigurationError(
                f"ERP profile v{profile.version} is missing a published prompt for stage {prompt_stage}. Configure and publish one in ERP Administration."
            )

        template_values = {
            "erp_name": erp_identity.display_name if erp_identity else "",
            "erp_vendor": erp_identity.vendor if erp_identity else "",
            "erp_version": erp_identity.product_version if erp_identity else "",
            "profile_version": str(profile.version),
            "project_name": project.name,
            "requirement": project.business_requirement,
            "stage": stage,
            "current_task": current_task,
        }
        rendered_prompts = []
        for prompt in prompts:
            validate_prompt_template(prompt.content, prompt.variables or [])

            def replace_variable(match):
                name = match.group(1)
                if name not in template_values:
                    raise PromptConfigurationError(
                        f"Prompt '{prompt.name}' uses unsupported placeholder '{{{{{name}}}}}'."
                    )
                return template_values[name]

            rendered_prompts.append(
                (prompt, re.sub(r"{{\s*([a-zA-Z0-9_]+)\s*}}", replace_variable, prompt.content))
            )

        query_text = " ".join(
            [project.name, project.business_requirement, stage, current_task]
        ).lower()
        assets_result = await self.db.execute(
            select(ERPAssetVersion).where(
                ERPAssetVersion.profile_version_id == profile.id,
                ERPAssetVersion.status == "PUBLISHED",
            )
        )
        assets = list(assets_result.scalars())
        selected_assets = sorted(
            assets,
            key=lambda a: _relevance(query_text, a.name, a.description, a.text_content),
            reverse=True,
        )
        selected_assets = [
            a
            for a in selected_assets
            if _relevance(query_text, a.name, a.description, a.text_content) > 0
        ][:6]

        feedback_result = await self.db.execute(
            select(FeedbackGuidance).where(
                FeedbackGuidance.status == "APPROVED",
                or_(
                    and_(
                        FeedbackGuidance.scope == "PROJECT",
                        FeedbackGuidance.project_id == project.id,
                        FeedbackGuidance.client_id == project.client_id,
                    ),
                    and_(
                        FeedbackGuidance.scope == "ERP",
                        FeedbackGuidance.project_id.is_(None),
                        FeedbackGuidance.client_id.is_(None),
                        FeedbackGuidance.profile_id == profile.profile_id,
                    ),
                    and_(
                        FeedbackGuidance.scope == "GLOBAL",
                        FeedbackGuidance.project_id.is_(None),
                        FeedbackGuidance.client_id.is_(None),
                        FeedbackGuidance.profile_id.is_(None),
                    ),
                ),
                or_(FeedbackGuidance.stage.is_(None), FeedbackGuidance.stage == stage),
            )
        )
        feedback = list(feedback_result.scalars())
        feedback = sorted(
            (x for x in feedback if _relevance(query_text, x.content) > 0),
            key=lambda x: _relevance(query_text, x.content),
            reverse=True,
        )[:5]

        prompt_text = "\n\n".join(
            f"[{p.scope} PROMPT: {p.name} v{p.version}]\n{rendered}"
            for p, rendered in rendered_prompts
        )
        knowledge = [a for a in selected_assets if a.asset_kind == "KNOWLEDGE"]
        packages = [a for a in selected_assets if a.asset_kind == "PACKAGE"]
        system_parts = [prompt_text]
        if feedback:
            system_parts.append(
                "APPROVED REVIEW GUIDANCE:\n" + "\n".join(f"- {x.content}" for x in feedback)
            )
        if knowledge:
            system_parts.append(
                "RETRIEVED ERP KNOWLEDGE:\n"
                + "\n".join(_asset_context(a, query_text) for a in knowledge)
            )
        if packages:
            system_parts.append(
                "RETRIEVED STANDARD PACKAGE ASSETS:\n"
                + "\n".join(_asset_context(a, query_text) for a in packages)
            )

        prompt_refs = [
            {
                "id": p.id,
                "scope": p.scope,
                "name": p.name,
                "stage": p.stage,
                "version": p.version,
                "content": p.content,
            }
            for p in prompts
        ]
        asset_refs = [
            {
                "id": a.id,
                "asset_id": a.asset_id,
                "kind": a.asset_kind,
                "name": a.name,
                "version": a.version,
                "checksum": a.checksum,
            }
            for a in selected_assets
        ]
        feedback_refs = [{"id": x.id, "scope": x.scope, "version": x.version} for x in feedback]
        context_payload = {
            "erp": {
                "name": erp_identity.display_name if erp_identity else "",
                "vendor": erp_identity.vendor if erp_identity else "",
                "version_label": erp_identity.product_version if erp_identity else "",
                "profile_version_id": profile.id,
                "version": profile.version,
            },
            "stage": stage,
            "requirement": project.business_requirement,
            "schema_context": project.erp_schema_context,
            "approved_upstream_artifacts": upstream,
            "reviewer_guidance": [x.content for x in feedback],
            "knowledge": [_asset_payload(x, query_text) for x in knowledge],
            "standard_packages": [_asset_payload(x, query_text) for x in packages],
            "current_task": current_task,
        }
        if integration_pattern:
            context_payload["integration_pattern"] = integration_pattern
        user_prompt = _render_context(context_payload)
        provenance = {
            "erp_profile": {
                "id": profile.profile_id,
                "version_id": profile.id,
                "version": profile.version,
            },
            "prompt_versions": prompt_refs,
            "knowledge_asset_versions": [x for x in asset_refs if x["kind"] == "KNOWLEDGE"],
            "standard_package_versions": [x for x in asset_refs if x["kind"] == "PACKAGE"],
            "feedback_versions": feedback_refs,
            "requirement_version": project.requirement_version,
            "schema_context_version": project.schema_context_version,
            "upstream_artifacts": {key: item.get("version_id") for key, item in upstream.items()},
            "generation_configuration": profile.configuration.get("generation", {}),
        }
        if integration_pattern:
            provenance["integration_pattern"] = {
                key: value for key, value in integration_pattern.items() if key != "baselines"
            }
            provenance["baseline_versions"] = integration_pattern["baseline_versions"]
            provenance["generation_strategy_version"] = (
                integration_pattern["configuration"]
                .get("generation_rules", {})
                .get("strategy_version")
            )
        return CompiledGenerationContext(
            "\n\n".join(system_parts), user_prompt, provenance, profile, integration_pattern
        )

    @staticmethod
    def _stage_config(profile: ERPProfileVersion, stage: str) -> dict:
        for item in profile.configuration.get("workflow", {}).get("stages", []):
            if item.get("type") == stage:
                return item
        raise PromptConfigurationError(
            f"Stage {stage} is not configured in this ERP profile version."
        )


def _relevance(query: str, *fields: str | None) -> int:
    # ponytail: lexical ranking in memory; use an indexed retriever when the asset library grows.
    words = set(re.findall(r"[a-z0-9_]{3,}", query.lower()))
    source = " ".join(x or "" for x in fields).lower()
    return len(words.intersection(re.findall(r"[a-z0-9_]{3,}", source)))


def _asset_payload(asset: ERPAssetVersion, query: str = "") -> dict:
    text = _relevant_asset_text(asset.text_content or "", query)
    metadata = dict(asset.metadata_json or {})
    if isinstance(metadata.get("files"), list):
        metadata["files"] = [
            {
                key: file.get(key)
                for key in ("file_name", "mime_type", "checksum", "size")
                if key in file
            }
            for file in metadata["files"]
            if isinstance(file, dict)
        ]
    return {
        "name": asset.name,
        "description": asset.description,
        "package_type": asset.package_type,
        "file_name": asset.file_name,
        "content": text,
        "metadata": metadata,
    }


def _asset_context(asset: ERPAssetVersion, query: str = "") -> str:
    payload = _asset_payload(asset, query)
    return f"{asset.name} v{asset.version} ({asset.file_name or asset.package_type or asset.asset_kind})\n{payload['description'] or ''}\n{payload['content']}"


def _relevant_asset_text(content: str, query: str) -> str:
    if len(content) <= 12000:
        return content
    sections = re.split(r"(?m)(?=^### )", content)
    if len(sections) <= 1 or not query:
        return content[:12000]
    ranked = sorted(
        enumerate(sections), key=lambda item: (_relevance(query, item[1]), -item[0]), reverse=True
    )
    selected = []
    remaining = 12000
    for _, section in ranked:
        excerpt = section[:remaining]
        if excerpt:
            selected.append(excerpt)
            remaining -= len(excerpt)
        if remaining <= 0:
            break
    return "\n\n".join(selected)


def _render_context(data: dict) -> str:
    import json

    return (
        "Use the following versioned generation context as the source of truth. "
        "Do not infer unsupported ERP facts.\n\n" + json.dumps(data, indent=2)
    )
