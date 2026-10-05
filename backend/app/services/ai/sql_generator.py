"""
HighStudio — SQL Generation AI Pipeline

Generates the extraction SQL from the approved TDD and FDD.
Gate 4 in the workflow.
"""

import json
import logging

from app.services.llm.base import LLMProvider, LLMRequest

logger = logging.getLogger("erpfusion.ai.sql")



async def run_sql_generation(
    tdd_content: dict,
    fdd_content: dict,
    erp_schema_context: dict,
    llm: LLMProvider,
    system_prompt: str,
) -> dict:
    """Generate extraction SQL from approved TDD."""
    # The TDD already carries FDD lineage and the full approved documents can
    # be large. Keep only the sections required to produce SQL so that the
    # provider receives one compact, consistent source of truth.
    tdd_sections = (
        "technical_architecture", "source_entities", "entity_relationships",
        "sql_design", "input_parameters", "extraction_modes",
        "incremental_logic", "sanitization_design", "file_generation",
    )
    fdd_sections = (
        "business_scope", "attribute_mappings", "business_rules",
        "sanitization_rules", "output_specification",
    )
    compact_tdd = {key: tdd_content[key] for key in tdd_sections if key in tdd_content}
    compact_fdd = {key: fdd_content[key] for key in fdd_sections if key in fdd_content}
    user_prompt = f"""## Approved TDD
{json.dumps(compact_tdd, indent=2)}

## Approved FDD
{json.dumps(compact_fdd, indent=2)}

## ERP Schema Context
{json.dumps(erp_schema_context, indent=2)}

## Task
Generate the complete Oracle extraction SQL based on the approved TDD.
Produce three variants: FULL, DELTA, and SELECTIVE modes.
Apply sanitization (REPLACE CHR(10), CHR(13), delimiter) to all text columns.
Return ONLY the JSON object as specified in the system prompt."""

    request = LLMRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=4096,
    )

    logger.info("Running SQL generation pipeline...")
    result = await llm.generate_json(request)
    logger.info(f"SQL generated: {result.get('column_count', '?')} columns, {result.get('join_count', '?')} joins")
    return result
