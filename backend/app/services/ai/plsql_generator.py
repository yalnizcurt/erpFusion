"""
erpFusion — PL/SQL Package Generation AI Pipeline

Generates complete .pks (specification) and .pkb (body) files from the
approved TDD, SQL, and FDD.

Gate 5 in the workflow. Generates PKS and PKB together.
"""

import json
import logging
import re

from app.services.llm.base import LLMProvider, LLMRequest

logger = logging.getLogger("erpfusion.ai.plsql")



async def run_plsql_generation(
    tdd_content: dict,
    sql_content: dict,
    fdd_content: dict,
    erp_schema_context: dict,
    llm: LLMProvider,
    system_prompt: str,
    artifact_stage: str = "PACKAGE",
    existing_package: dict | None = None,
) -> dict:
    """Generate the configured package artifact stage from approved TDD and SQL."""
    artifact_stage = artifact_stage.upper()
    if artifact_stage not in {"PKS", "PKB", "PACKAGE"}:
        raise ValueError(f"Unsupported PL/SQL generation stage: {artifact_stage}")
    tdd_sections = (
        "technical_architecture", "source_entities", "entity_relationships",
        "sql_design", "input_parameters", "extraction_modes",
        "incremental_logic", "sanitization_design", "file_generation",
        "logging_design", "exception_handling", "deployment_considerations",
    )
    compact_tdd = {key: tdd_content[key] for key in tdd_sections if key in tdd_content}
    approved_query = sql_content.get("full_mode_sql") or sql_content.get("extraction_sql", "")
    selected_columns = re.findall(r"\bAS\s+\"?([A-Za-z][A-Za-z0-9_$#]*)\"?", approved_query, re.IGNORECASE)
    from_clause = re.search(r"\bFROM\b[\s\S]*", approved_query, re.IGNORECASE)
    compact_query = (
        "SELECT " + ", ".join(selected_columns) + "\n" + re.sub(r"\s+", " ", from_clause.group(0))
        if selected_columns and from_clause else re.sub(r"\s+", " ", approved_query)
    )
    compact_sql = {
        "approved_query_shape": compact_query,
        "bind_variables": sql_content.get("bind_variables", []),
        "sanitized_columns": sql_content.get("sanitized_columns", []),
    }
    compact_fdd = {"business_scope": fdd_content.get("business_scope", {})} if artifact_stage == "PACKAGE" else {}
    if artifact_stage == "PKS":
        compact_tdd = {
            key: compact_tdd[key] for key in ("technical_architecture", "input_parameters", "extraction_modes")
            if key in compact_tdd
        }
    elif artifact_stage == "PKB":
        compact_tdd = {
            key: compact_tdd[key] for key in (
                "technical_architecture", "source_entities", "entity_relationships", "sql_design",
                "input_parameters", "extraction_modes", "incremental_logic", "sanitization_design",
                "file_generation", "logging_design", "exception_handling", "deployment_considerations",
            ) if key in compact_tdd
        }
    task_instruction = {
        "PKS": "Generate only the package specification (.pks). Set pkb_content to an empty string.",
        "PKB": "Generate only a concise, compilable package body (.pkb), implementing the supplied approved specification exactly. Set pks_content to the supplied approved specification. Use one parameterized static cursor and avoid duplicating query code across modes.",
        "PACKAGE": "Generate the package specification (.pks) and body (.pkb).",
    }[artifact_stage]
    output_contract = (
        "Return only the complete raw PL/SQL package body, without JSON, markdown fences, or explanation."
        if artifact_stage == "PKB" else "Return ONLY the JSON object specified in the system prompt."
    )
    user_prompt = f"""## Approved TDD
{json.dumps(compact_tdd, separators=(',', ':'))}

## Approved SQL
{json.dumps(compact_sql, separators=(',', ':'))}

## Approved FDD
{json.dumps(compact_fdd, separators=(',', ':')) if artifact_stage == 'PACKAGE' else '{}'}

## ERP Schema Context
{json.dumps(erp_schema_context, separators=(',', ':')) if artifact_stage != 'PKB' else '{}'}

## Task
{task_instruction}

Follow the approved profile, TDD and SQL exactly. Do not invent status codes,
tables, logging routines, directory objects, column types or defaults. For
unconfigured infrastructure, list explicit deployment prerequisites and do not
claim the package is production-ready. Preserve required runtime parameters
for unresolved values. Generate compilable Oracle PL/SQL: use cursor FOR loops
over explicit cursors (never TABLE(cursor)), named PL/SQL types (never inline
RECORD declarations), and valid static SQL where dependencies are configured.
Do not mark a feature implemented when it is only a prerequisite.
{output_contract}"""
    if existing_package:
        user_prompt += "\n\n## Approved package specification\n" + str(existing_package.get("pks_content", ""))

    request = LLMRequest(
        system_prompt=(system_prompt + "\n\nFor this PKB code artifact, return only complete raw Oracle PL/SQL package-body source as plain text; preserve all configured business rules and reviewer guidance.")
        if artifact_stage == "PKB" else system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        # Leave enough headroom for small Groq TPM tiers while keeping the
        # response budget large enough for one package artifact at a time.
        max_tokens=4600,
        response_format="text" if artifact_stage == "PKB" else "json_object",
    )

    logger.info("PL/SQL %s request context: system_chars=%s user_chars=%s",
                artifact_stage, len(system_prompt), len(user_prompt))
    logger.info("Running PL/SQL generation pipeline...")
    if artifact_stage == "PKB":
        response = await llm.generate(request)
        result = _package_body_result(response.content, existing_package or {})
    else:
        result = await llm.generate_json(request)
    logger.info(f"PL/SQL generated: package={result.get('package_name', 'unknown')}")
    return result


def _package_body_result(raw_content: str, existing_package: dict) -> dict:
    """Wrap plain code output in the stable artifact contract used by the UI."""
    content = raw_content.strip()
    if content.startswith("```"):
        content = "\n".join(line for line in content.splitlines() if not line.strip().startswith("```"))
    # Retain compatibility with providers that return the prior JSON contract
    # even when a plain-text response was requested (including the demo provider).
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        body = str(parsed.get("pkb_content") or "").strip()
        if not body:
            raise ValueError("PL/SQL generation returned JSON without a package body.")
        result = dict(parsed)
        result["pks_content"] = existing_package.get("pks_content", "")
    else:
        match = re.search(r"CREATE\s+(?:OR\s+REPLACE\s+)?PACKAGE\s+BODY\s+([A-Za-z][A-Za-z0-9_$#]*)", content, re.IGNORECASE)
        if not match:
            raise ValueError("PL/SQL generation did not return a package body source file.")
        package_name = match.group(1)
        expected_match = re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?PACKAGE\s+([A-Za-z][A-Za-z0-9_$#]*)\s+(?:IS|AS)",
            str(existing_package.get("pks_content", "")), re.IGNORECASE,
        )
        if expected_match and package_name.lower() != expected_match.group(1).lower():
            raise ValueError("Generated package body name does not match the approved package specification.")
        if not re.search(rf"\bEND\s+{re.escape(package_name)}\s*;", content, re.IGNORECASE):
            raise ValueError("PL/SQL generation returned an incomplete package body.")
        result = {
            "package_name": package_name,
            "pks_content": str(existing_package.get("pks_content", "")),
            "pkb_content": content,
            "procedures": _procedures_from_spec(str(existing_package.get("pks_content", ""))),
            "features_implemented": _implemented_features(content),
            "compilation_notes": _compilation_notes(content),
        }
    result["pkb_content"] = body if isinstance(parsed, dict) else result["pkb_content"]
    return result


def _procedures_from_spec(specification: str) -> list[dict]:
    procedures = []
    for match in re.finditer(r"\bPROCEDURE\s+([A-Za-z][A-Za-z0-9_$#]*)\s*\((.*?)\)\s*;", specification, re.IGNORECASE | re.DOTALL):
        parameters = [line.strip().rstrip(",") for line in match.group(2).splitlines() if line.strip()]
        procedures.append({"name": match.group(1), "visibility": "PUBLIC", "parameters": parameters})
    return procedures


def _implemented_features(body: str) -> dict:
    upper = body.upper()
    return {
        "extraction_modes": [mode for mode in ("FULL", "DELTA", "SELECTIVE") if mode in upper],
        "sanitization": bool(re.search(r"\bFUNCTION\s+SANITIZE\b|REPLACE\s*\(", upper)),
        "watermark_management": "WATERMARK" in upper,
        "file_generation": "UTL_FILE" in upper,
        "error_handling": "WHEN OTHERS" in upper,
        "logging": "LOG_ETL_EVENT" in upper,
        "header_record": "HEADER" in upper and "PUT_LINE" in upper,
    }


def _compilation_notes(body: str) -> list[str]:
    upper = body.upper()
    notes = []
    if "DIR_SUPPLIER_INVOICES" in upper:
        notes.append("Requires Oracle DIRECTORY object DIR_SUPPLIER_INVOICES with write access for the executing schema.")
    if "ETL_WATERMARKS" in upper:
        notes.append("Requires ETL_WATERMARKS table with columns and transaction ownership confirmed for this environment.")
    if "LOG_ETL_EVENT" in upper:
        notes.append("Requires the configured log_etl_event procedure with a signature matching the calls in the package body.")
    if "TO_DATE(" in upper or "TO_TIMESTAMP(" in upper or "TO_CHAR(" in upper:
        notes.append("Confirm source column types and date/number formatting against the target ERP schema before deployment.")
    return notes
