"""
HighStudio — TDD Generation AI Pipeline

Generates a Technical Design Document from the approved FDD,
context analysis, and ERP schema context.

Gate 3 in the workflow.
"""

import json
import logging

from app.services.llm.base import LLMProvider, LLMRequest

logger = logging.getLogger("erpfusion.ai.tdd")



async def run_tdd_generation(
    business_requirement: str,
    erp_schema_context: dict,
    context_analysis: dict,
    fdd_content: dict,
    llm: LLMProvider,
    system_prompt: str,
) -> dict:
    """Generate a TDD from approved FDD and context analysis."""
    user_prompt = f"""## Business Requirement
{business_requirement}

## Approved Context Analysis
{json.dumps(context_analysis, indent=2)}

## Approved FDD
{json.dumps(fdd_content, indent=2)}

## ERP Schema Context
{json.dumps(erp_schema_context, indent=2)}

## Task
Generate a complete Technical Design Document (TDD) that translates the approved FDD
into a detailed Oracle PL/SQL implementation design.
Include exact SQL design, join conditions, package structure, parameters,
incremental logic, sanitization, file generation, and error handling.
Return ONLY the JSON object as specified in the system prompt."""

    request = LLMRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.15,
        max_tokens=16384,
    )

    logger.info("Running TDD generation pipeline...")
    result = await llm.generate_json(request)
    logger.info("TDD generation completed")
    return result
