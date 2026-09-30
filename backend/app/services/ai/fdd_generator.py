"""
erpFusion — FDD Generation AI Pipeline

Generates a Functional Design Document from the approved Context Analysis,
business requirement, and ERP schema context.

This is Gate 2 in the workflow.
"""

import json
import logging

from app.services.llm.base import LLMProvider, LLMRequest

logger = logging.getLogger("erpfusion.ai.fdd")



async def run_fdd_generation(
    business_requirement: str,
    erp_schema_context: dict,
    context_analysis: dict,
    llm: LLMProvider,
    system_prompt: str,
) -> dict:
    """
    Generate an FDD from approved context analysis.

    Args:
        business_requirement: Original requirement text
        erp_schema_context: ERP schema context
        context_analysis: Approved context analysis content
        llm: LLM provider

    Returns:
        Structured FDD content as a dict
    """
    user_prompt = f"""## Business Requirement
{business_requirement}

## Approved Context Analysis
{json.dumps(context_analysis, indent=2)}

## ERP Schema Context
{json.dumps(erp_schema_context, indent=2)}

## Task
Generate a complete Functional Design Document (FDD) based on the approved context analysis.
Map every business attribute to its source table and column.
Define extraction modes, business rules, sanitization rules, and output specification.
Return ONLY the JSON object as specified in the system prompt."""

    request = LLMRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.15,
        max_tokens=16384,
    )

    logger.info("Running FDD generation pipeline...")
    result = await llm.generate_json(request)
    logger.info(
        f"FDD generated: {len(result.get('attribute_mappings', []))} mappings, "
        f"{len(result.get('business_rules', []))} rules"
    )
    return result
