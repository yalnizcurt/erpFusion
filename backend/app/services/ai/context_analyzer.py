"""
erpFusion — Context Analysis AI Pipeline

Given a business requirement + ERP schema context, produces a structured
analysis identifying entities, relationships, extraction modes, assumptions,
and ambiguities.

This is the first AI pipeline — Gate 1 in the workflow.
"""

import json
import logging

from app.services.llm.base import LLMProvider, LLMRequest

logger = logging.getLogger("erpfusion.ai.context")



async def run_context_analysis(
    business_requirement: str,
    erp_schema_context: dict,
    llm: LLMProvider,
    system_prompt: str,
) -> dict:
    """
    Run the Context Analysis AI pipeline.

    Args:
        business_requirement: The business requirement text
        erp_schema_context: The ERP schema context JSON
        llm: The LLM provider to use

    Returns:
        Structured context analysis as a dict
    """
    user_prompt = f"""## Business Requirement
{business_requirement}

## ERP Schema Context
{json.dumps(erp_schema_context, indent=2)}

## Task
Analyze the above business requirement against the ERP schema context.
Identify all relevant entities, relationships, extraction modes, assumptions, and ambiguities.
Return ONLY the JSON object as specified in the system prompt."""

    request = LLMRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.15,
        max_tokens=8192,
    )

    logger.info("Running context analysis pipeline...")
    result = await llm.generate_json(request)
    logger.info(
        f"Context analysis complete: "
        f"{len(result.get('identified_entities', []))} entities, "
        f"{len(result.get('relationships', []))} relationships, "
        f"{len(result.get('assumptions', []))} assumptions, "
        f"{len(result.get('ambiguities', []))} ambiguities"
    )
    return result
