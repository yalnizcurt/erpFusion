"""Configured generation strategy adapters, independent of ERP identity."""

from abc import ABC, abstractmethod

from app.models import Project
from app.services.ai import (
    run_context_analysis, run_deployment_generation, run_fdd_generation,
    run_plsql_generation, run_sql_generation, run_tdd_generation,
)
from app.services.llm.base import LLMProvider, LLMRequest
from app.services.prompt_compiler import CompiledGenerationContext


class GenerationStrategy(ABC):
    @abstractmethod
    async def generate(self, project: Project, stage: str, upstream: dict,
                       context: CompiledGenerationContext, llm: LLMProvider) -> dict:
        raise NotImplementedError


class GenericJSONStrategy(GenerationStrategy):
    async def generate(self, project, stage, upstream, context, llm):
        generation_config = context.profile_version.configuration.get("generation", {})
        temperature = min(2.0, max(0.0, float(generation_config.get("temperature", 0.15))))
        max_tokens = min(128000, max(1, int(generation_config.get("max_tokens", 16384))))
        configured_demo = getattr(llm, "generate_configured_json", None)
        if configured_demo is not None:
            return await configured_demo(LLMRequest(
                system_prompt=context.system_prompt,
                user_prompt=context.user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            ))
        result = await llm.generate_json(LLMRequest(
            system_prompt=context.system_prompt,
            user_prompt=context.user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ))
        return result


class OraclePLSQLStrategy(GenerationStrategy):
    """Compatibility adapter for the seeded Oracle prompt/package contract."""
    async def generate(self, project, stage, upstream, context, llm):
        requirement = project.business_requirement
        schema = project.erp_schema_context
        if stage == "CONTEXT_ANALYSIS":
            return await run_context_analysis(requirement, schema, llm, context.system_prompt)
        if stage == "FDD":
            return await run_fdd_generation(requirement, schema, upstream.get("CONTEXT_ANALYSIS", {}).get("content", {}), llm, context.system_prompt)
        if stage == "TDD":
            return await run_tdd_generation(requirement, schema,
                upstream.get("CONTEXT_ANALYSIS", {}).get("content", {}),
                upstream.get("FDD", {}).get("content", {}), llm, context.system_prompt)
        if stage == "SQL":
            return await run_sql_generation(upstream.get("TDD", {}).get("content", {}),
                upstream.get("FDD", {}).get("content", {}), schema, llm, context.system_prompt)
        if stage in {"PKS", "PKB"}:
            existing = upstream.get("PKS", {}).get("content", {})
            return await run_plsql_generation(
                upstream.get("TDD", {}).get("content", {}), upstream.get("SQL", {}).get("content", {}),
                upstream.get("FDD", {}).get("content", {}), schema, llm, context.system_prompt,
                artifact_stage=stage, existing_package=existing if stage == "PKB" else None)
        if stage == "DEPLOYMENT":
            return await run_deployment_generation(
                upstream.get("TDD", {}).get("content", {}), upstream.get("SQL", {}).get("content", {}),
                upstream.get("PKB", {}).get("content", {}) or upstream.get("PKS", {}).get("content", {}),
                llm, context.system_prompt)
        raise ValueError(f"Oracle PL/SQL strategy does not implement configured stage {stage}")


STRATEGY_ADAPTERS: dict[str, GenerationStrategy] = {
    "generic_json": GenericJSONStrategy(),
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
        raise ValueError(f"Generation adapter '{adapter}' is not installed. Configure an available adapter or install a strategy plugin.")
    return strategy
