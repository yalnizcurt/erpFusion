"""Configured generation strategy adapters, independent of ERP identity."""

from abc import ABC, abstractmethod

from app.models import Project
from app.services.llm.base import LLMProvider, LLMRequest
from app.services.prompt_compiler import CompiledGenerationContext


class GenerationStrategy(ABC):
    supports_baseline = False

    @abstractmethod
    async def generate(
        self,
        project: Project,
        stage: str,
        upstream: dict,
        context: CompiledGenerationContext,
        llm: LLMProvider,
    ) -> dict:
        raise NotImplementedError


class GenericJSONStrategy(GenerationStrategy):
    async def generate(self, project, stage, upstream, context, llm):
        generation_config = context.profile_version.configuration.get("generation", {})
        temperature = min(2.0, max(0.0, float(generation_config.get("temperature", 0.15))))
        max_tokens = min(128000, max(1, int(generation_config.get("max_tokens", 16384))))
        configured_demo = getattr(llm, "generate_configured_json", None)
        if configured_demo is not None:
            return await configured_demo(
                LLMRequest(
                    system_prompt=context.system_prompt,
                    user_prompt=context.user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            )
        result = await llm.generate_json(
            LLMRequest(
                system_prompt=context.system_prompt,
                user_prompt=context.user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        return result


class OraclePLSQLStrategy(GenerationStrategy):
    """Compatibility adapter for the seeded Oracle prompt/package contract."""

    async def generate(self, project, stage, upstream, context, llm):
        config = context.profile_version.configuration.get("generation", {})
        return await llm.generate_json(
            LLMRequest(
                system_prompt=context.system_prompt,
                user_prompt=context.user_prompt,
                temperature=float(config.get("temperature", 0.15)),
                max_tokens=int(config.get("max_tokens", 16384)),
            )
        )


class BaselineJSONStrategy(GenericJSONStrategy):
    """Modify an approved named-file baseline within pattern-defined limits."""

    supports_baseline = True

    async def generate(self, project, stage, upstream, context, llm):
        from app.services.integration_patterns import apply_modifications, baseline_files

        if not context.integration_pattern:
            raise ValueError("integration_pattern_and_baseline_required")
        if getattr(llm, "model", "") == "mock":
            result = {
                "files": [
                    {"name": name, "content": content}
                    for name, content in baseline_files(context.integration_pattern).items()
                    if name
                    in context.integration_pattern["configuration"]["generation_rules"].get(
                        "allowed_files", []
                    )
                ]
            }
        else:
            result = await super().generate(project, stage, upstream, context, llm)
        result["files"] = apply_modifications(context.integration_pattern, result.get("files"))
        result["baseline_versions"] = context.integration_pattern["baseline_versions"]
        result["integration_pattern_version_id"] = context.integration_pattern["version_id"]
        return result


class PublisherSourceStrategy(GenericJSONStrategy):
    """Reviewable Publisher source contract, explicitly not a native .xdm export."""

    supports_baseline = True

    async def generate(self, project, stage, upstream, context, llm):
        import json

        from app.services.integration_patterns import apply_modifications, baseline_files

        if not context.integration_pattern:
            raise ValueError("publisher_pattern_and_baseline_required")
        result = await super().generate(project, stage, upstream, context, llm)
        query = result.get("sql_query", "")
        if getattr(llm, "model", "") == "mock":
            query = baseline_files(context.integration_pattern).get("extract.sql", "")
        if not isinstance(query, str) or not query.lstrip().upper().startswith("SELECT "):
            raise ValueError("publisher_select_query_required")
        contract = {
            "format": "publisher-source-v1",
            "native_import": "UNQUALIFIED",
            "sql_query": query,
            "design": result,
        }
        return {
            **result,
            "artifact_contract": "publisher-source-v1",
            "native_import_qualification": "NOT_VERIFIED",
            "files": apply_modifications(
                context.integration_pattern,
                [
                    {"name": "extract.sql", "content": query},
                    {
                        "name": "publisher-source.json",
                        "content": json.dumps(contract, sort_keys=True),
                    },
                ],
            ),
            "baseline_versions": context.integration_pattern["baseline_versions"],
            "integration_pattern_version_id": context.integration_pattern["version_id"],
        }


STRATEGY_ADAPTERS: dict[str, GenerationStrategy] = {
    "generic_json": GenericJSONStrategy(),
    "baseline_json": BaselineJSONStrategy(),
    "publisher_source": PublisherSourceStrategy(),
    "oracle_context_analysis": OraclePLSQLStrategy(),
    "oracle_fdd": OraclePLSQLStrategy(),
    "oracle_tdd": OraclePLSQLStrategy(),
    "oracle_sql": OraclePLSQLStrategy(),
    "oracle_plsql": OraclePLSQLStrategy(),
    "oracle_deployment": OraclePLSQLStrategy(),
}


def get_strategy(adapter: str) -> GenerationStrategy:
    strategy = STRATEGY_ADAPTERS.get(adapter)
    if strategy is None:
        raise ValueError(
            f"Generation adapter '{adapter}' is not installed. "
            "Configure an available adapter or install a strategy plugin."
        )
    return strategy
