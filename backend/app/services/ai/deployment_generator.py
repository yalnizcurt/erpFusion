"""
erpFusion — Deployment Package Generator AI Pipeline

Generates a complete deployment package including installation instructions,
compilation order, grants, synonyms, verification scripts, and rollback procedures
from the approved PL/SQL, SQL, and TDD artifacts.

Gate 6 in the workflow.
"""

import json
import logging
from typing import Any, Dict

from app.services.llm.base import LLMProvider, LLMRequest

logger = logging.getLogger("erpfusion.ai.deployment")



async def run_deployment_generation(
    tdd_content: Dict[str, Any],
    sql_content: Dict[str, Any],
    plsql_content: Dict[str, Any],
    llm: LLMProvider,
    system_prompt: str,
) -> Dict[str, Any]:
    """Generate deployment package from approved TDD, SQL, and PLSQL artifacts."""
    package_name = plsql_content.get("package_name") or tdd_content.get("technical_architecture", {}).get("package_name", "XX_ERP_INTEGRATION_PKG")

    user_prompt = f"""## Package Name
{package_name}

## Approved TDD Architecture
{json.dumps(tdd_content.get("technical_architecture", {}), indent=2)}

## Implemented Procedures
{json.dumps(plsql_content.get("procedures", []), indent=2)}

## Features Implemented
{json.dumps(plsql_content.get("features_implemented", {}), indent=2)}

## Task
Generate a complete, enterprise-grade deployment package for {package_name}.
Include prerequisites, compilation sequence, grants/synonyms, verification test scripts, and rollback procedures.
Return ONLY the JSON object as specified in the system prompt."""

    request = LLMRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.15,
        max_tokens=8192,
    )

    logger.info("Running deployment generation pipeline...")
    result = await llm.generate_json(request)
    logger.info(f"Deployment package generated for {package_name}")
    return result
