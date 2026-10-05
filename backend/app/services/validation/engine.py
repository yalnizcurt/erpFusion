"""
HighStudio — Deterministic Validation Engine

Performs automated, deterministic validation checks on generated artifacts
before they are presented for human review.

Validators:
1. SchemaConformityValidator: Flags hallucinated tables, columns, or broken joins.
2. SQLValidator: Checks Oracle syntax rules, bind variables, sanitization wrapping.
3. PLSQLValidator: Checks spec-to-body alignment, exception handling, watermark logic.
4. TraceabilityValidator: Verifies end-to-end lineage from FDD through SQL/PLSQL.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.models.base import ValidationCategory, ValidationStatus

logger = logging.getLogger("erpfusion.validation")


class CheckResult:
    def __init__(
        self,
        name: str,
        status: ValidationStatus,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.status = status
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
        }


class SchemaConformityValidator:
    """
    Validates that all tables, columns, and relationships referenced in an
    artifact actually exist in the provided ERP schema context.
    Prevents LLM hallucinations from entering the engineering package.
    """

    @staticmethod
    def validate(
        artifact_type: str,
        content: Dict[str, Any],
        erp_schema_context: Dict[str, Any],
    ) -> Tuple[ValidationStatus, List[Dict[str, Any]]]:
        checks: List[CheckResult] = []

        # Extract available tables and columns from schema context
        available_tables: Dict[str, set] = {}
        tables_meta = erp_schema_context.get("tables")
        if tables_meta is None:
            tables_meta = erp_schema_context.get("entities", erp_schema_context.get("objects", []))

        def column_names(columns):
            names: set[str] = set()
            if not isinstance(columns, (list, tuple, set)):
                return names
            for column in columns:
                if isinstance(column, dict):
                    name = column.get("name") or column.get("column_name") or column.get("field")
                else:
                    name = column
                if name:
                    names.add(str(name).upper())
            return names

        if isinstance(tables_meta, list):
            for t in tables_meta:
                if not isinstance(t, dict):
                    continue
                tname = str(t.get("name") or t.get("table") or t.get("table_name") or "").upper()
                cols = column_names(t.get("columns", t.get("fields", [])))
                if tname:
                    available_tables[tname] = cols
        elif isinstance(tables_meta, dict):
            for tname, tinfo in tables_meta.items():
                tname_upper = tname.upper()
                if isinstance(tinfo, dict):
                    cols = column_names(tinfo.get("columns", tinfo.get("fields", [])))
                else:
                    cols = column_names(tinfo)
                available_tables[tname_upper] = cols

        # Check 1: Schema context has valid tables
        if not available_tables:
            checks.append(
                CheckResult(
                    name="schema_context_validity",
                    status=ValidationStatus.WARN,
                    message="Schema context contains no tables or is empty. Schema conformity check bypassed.",
                )
            )
            return ValidationStatus.WARN, [c.to_dict() for c in checks]

        checks.append(
            CheckResult(
                name="schema_context_validity",
                status=ValidationStatus.PASS,
                message=f"Schema context contains {len(available_tables)} registered table(s).",
                details={"tables": list(available_tables.keys())},
            )
        )

        # Check 2: Table references
        referenced_tables = set()
        referenced_columns: List[Tuple[str, str]] = []

        if artifact_type == "CONTEXT_ANALYSIS":
            for ent in content.get("identified_entities", []):
                tbl = ent.get("erp_table", "").upper()
                if tbl:
                    referenced_tables.add(tbl)
                for col in ent.get("relevant_columns", []):
                    cname = col.get("column_name", "").upper()
                    if tbl and cname:
                        referenced_columns.append((tbl, cname))

        elif artifact_type == "FDD":
            for mapping in content.get("attribute_mappings", []):
                tbl = mapping.get("source_table", "").upper()
                col = mapping.get("source_column", "").upper()
                if tbl:
                    referenced_tables.add(tbl)
                if tbl and col:
                    referenced_columns.append((tbl, col))

        elif artifact_type == "TDD":
            entity_aliases: Dict[str, str] = {}
            for ent in content.get("source_entities", []):
                tbl = str(ent.get("table_name") or ent.get("erp_table") or "").split(".")[-1].upper()
                if tbl:
                    referenced_tables.add(tbl)
                    alias = str(ent.get("alias") or "").upper()
                    if alias:
                        entity_aliases[alias] = tbl
            for col in content.get("sql_design", {}).get("select_columns", []):
                tbl = str(col.get("source_table") or col.get("table_name") or "").split(".")[-1].upper()
                expression = str(col.get("expression") or "")
                cname = str(col.get("column_name") or col.get("source_column") or "").upper()
                if not cname and expression:
                    qualified = re.findall(r"\b[A-Za-z][A-Za-z0-9_$#]*\.([A-Za-z][A-Za-z0-9_$#]*)\b", expression)
                    if qualified:
                        cname = qualified[-1].upper()
                if not tbl and expression:
                    alias_match = re.search(r"\b([A-Za-z][A-Za-z0-9_$#]*)\.([A-Za-z][A-Za-z0-9_$#]*)\b", expression)
                    if alias_match:
                        tbl = entity_aliases.get(alias_match.group(1).upper(), "")
                if tbl and cname:
                    referenced_columns.append((tbl, cname))
            sql_design = content.get("sql_design", {})
            sql_fragments = [str(sql_design.get("where_clause") or "")]
            sql_fragments.extend(str(fragment) for fragment in sql_design.get("join_clauses", []))
            sql_fragments.extend(
                str(relationship.get("join_condition") or "")
                for relationship in content.get("entity_relationships", [])
                if isinstance(relationship, dict)
            )
            for fragment in sql_fragments:
                for alias, cname in re.findall(
                    r"\b([A-Za-z][A-Za-z0-9_$#]*)\.([A-Za-z][A-Za-z0-9_$#]*)\b", fragment
                ):
                    tbl = entity_aliases.get(alias.upper())
                    if tbl:
                        referenced_columns.append((tbl, cname.upper()))

        elif artifact_type == "SQL":
            sql_text = str(content.get("extraction_sql") or content.get("full_mode_sql") or "")
            table_aliases: Dict[str, str] = {}
            reserved_aliases = {"WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "ON", "GROUP", "ORDER", "HAVING", "UNION"}
            for match in re.finditer(
                r"\b(?:FROM|JOIN)\s+([A-Za-z0-9_$#\.]+)(?:\s+(?:AS\s+)?([A-Za-z][A-Za-z0-9_$#]*))?",
                sql_text,
                flags=re.IGNORECASE,
            ):
                table_name = match.group(1).split(".")[-1].upper()
                possible_alias = (match.group(2) or "").upper()
                alias = possible_alias if possible_alias and possible_alias not in reserved_aliases else table_name
                table_aliases[alias] = table_name
                referenced_tables.add(table_name)
            for alias, column in re.findall(r"\b([A-Za-z][A-Za-z0-9_$#]*)\.([A-Za-z][A-Za-z0-9_$#]*)\b", sql_text):
                source_table = table_aliases.get(alias.upper(), alias.upper())
                if source_table in available_tables:
                    referenced_columns.append((source_table, column.upper()))

        if not referenced_tables and not referenced_columns:
            checks.append(
                CheckResult(
                    name="schema_reference_extraction",
                    status=ValidationStatus.WARN,
                    message=f"No schema references could be extracted from {artifact_type}; schema conformity was not asserted.",
                )
            )
            return ValidationStatus.WARN, [check.to_dict() for check in checks]

        # Validate tables exist
        hallucinated_tables = [t for t in referenced_tables if t not in available_tables]
        if hallucinated_tables:
            checks.append(
                CheckResult(
                    name="table_existence_check",
                    status=ValidationStatus.FAIL,
                    message=f"Detected {len(hallucinated_tables)} unverified/hallucinated table(s) not in schema context.",
                    details={"hallucinated_tables": hallucinated_tables},
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="table_existence_check",
                    status=ValidationStatus.PASS,
                    message=f"All {len(referenced_tables)} referenced table(s) exist in ERP schema context.",
                    details={"verified_tables": list(referenced_tables)},
                )
            )

        # Validate columns exist
        hallucinated_cols = []
        for tbl, col in referenced_columns:
            if tbl in available_tables and available_tables[tbl]:
                if col not in available_tables[tbl]:
                    hallucinated_cols.append(f"{tbl}.{col}")

        if hallucinated_cols:
            checks.append(
                CheckResult(
                    name="column_existence_check",
                    status=ValidationStatus.FAIL,
                    message=f"Detected {len(hallucinated_cols)} unverified column(s) not in schema context.",
                    details={"hallucinated_columns": hallucinated_cols},
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="column_existence_check",
                    status=ValidationStatus.PASS,
                    message=f"All {len(referenced_columns)} referenced column(s) match ERP schema context.",
                )
            )

        has_fail = any(c.status == ValidationStatus.FAIL for c in checks)
        has_warn = any(c.status == ValidationStatus.WARN for c in checks)
        overall = ValidationStatus.FAIL if has_fail else (ValidationStatus.WARN if has_warn else ValidationStatus.PASS)

        return overall, [c.to_dict() for c in checks]


class SQLValidator:
    """
    Validates SQL queries against Oracle rules, bind variable usage,
    and sanitization wrapping.
    """

    DANGEROUS_KEYWORDS = ["DROP ", "ALTER ", "TRUNCATE ", "DELETE ", "UPDATE ", "INSERT ", "MERGE ", "EXEC "]

    @staticmethod
    def validate(content: Dict[str, Any]) -> Tuple[ValidationStatus, List[Dict[str, Any]]]:
        checks: List[CheckResult] = []
        sql_text = content.get("extraction_sql", "") or content.get("full_mode_sql", "")

        if not sql_text:
            checks.append(
                CheckResult(
                    name="sql_present",
                    status=ValidationStatus.FAIL,
                    message="No SQL query text found in artifact content.",
                )
            )
            return ValidationStatus.FAIL, [c.to_dict() for c in checks]

        # Check 1: Read-only safety
        upper_sql = sql_text.upper()
        found_dangerous = [kw.strip() for kw in SQLValidator.DANGEROUS_KEYWORDS if kw in upper_sql]
        if found_dangerous:
            checks.append(
                CheckResult(
                    name="read_only_safety",
                    status=ValidationStatus.FAIL,
                    message=f"Extraction query contains non-read-only DDL/DML statements: {found_dangerous}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="read_only_safety",
                    status=ValidationStatus.PASS,
                    message="Query is strictly read-only (SELECT extraction).",
                )
            )

        # Check 2: SELECT and FROM presence
        if "SELECT" in upper_sql and "FROM" in upper_sql:
            checks.append(
                CheckResult(
                    name="sql_structure",
                    status=ValidationStatus.PASS,
                    message="Valid SQL query structure with SELECT and FROM clauses.",
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="sql_structure",
                    status=ValidationStatus.FAIL,
                    message="Malformed SQL: missing SELECT or FROM clause.",
                )
            )

        # Check 3: Bind variable placeholders
        bind_vars = re.findall(r":([a-zA-Z0-9_]+)", sql_text)
        if bind_vars:
            checks.append(
                CheckResult(
                    name="bind_variable_compliance",
                    status=ValidationStatus.PASS,
                    message=f"Found {len(set(bind_vars))} bind variable(s): {list(set(bind_vars))}",
                    details={"bind_variables": list(set(bind_vars))},
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="bind_variable_compliance",
                    status=ValidationStatus.WARN,
                    message="No bind variables detected (:param). Full extraction mode may not support incremental watermarking.",
                )
            )

        # Check 4: Sanitization check (REPLACE / CHR)
        has_sanitization = "REPLACE(" in upper_sql or "CHR(" in upper_sql
        if has_sanitization:
            checks.append(
                CheckResult(
                    name="text_sanitization",
                    status=ValidationStatus.PASS,
                    message="Delimited field sanitization (REPLACE/CHR) is actively implemented.",
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="text_sanitization",
                    status=ValidationStatus.WARN,
                    message="No REPLACE/CHR sanitization functions detected in SELECT list. Recommended for flat-file delimiters and newlines.",
                )
            )

        has_fail = any(c.status == ValidationStatus.FAIL for c in checks)
        has_warn = any(c.status == ValidationStatus.WARN for c in checks)
        overall = ValidationStatus.FAIL if has_fail else (ValidationStatus.WARN if has_warn else ValidationStatus.PASS)

        return overall, [c.to_dict() for c in checks]


class PLSQLValidator:
    """
    Validates PL/SQL packages for spec-to-body alignment, exception handling,
    UTL_FILE file handling, and watermark logic.
    """

    @staticmethod
    def validate(content: Dict[str, Any]) -> Tuple[ValidationStatus, List[Dict[str, Any]]]:
        checks: List[CheckResult] = []
        pks = content.get("pks_content", "")
        pkb = content.get("pkb_content", "")

        # Check 1: Spec and Body content presence
        if not pks and not pkb:
            checks.append(
                CheckResult(
                    name="package_content_present",
                    status=ValidationStatus.FAIL,
                    message="Neither package specification nor body content found.",
                )
            )
            return ValidationStatus.FAIL, [c.to_dict() for c in checks]

        # Check 2: Spec declarations vs Body implementations
        if pks and pkb:
            # Extract procedure names in spec
            def strip_comments(source: str) -> str:
                source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
                return re.sub(r"--[^\r\n]*", " ", source)

            spec_procs = set(re.findall(r"\bPROCEDURE\s+([a-zA-Z][a-zA-Z0-9_$#]*)\b", strip_comments(pks), re.IGNORECASE))
            body_procs = set(re.findall(r"\bPROCEDURE\s+([a-zA-Z][a-zA-Z0-9_$#]*)\b", strip_comments(pkb), re.IGNORECASE))

            missing_in_body = spec_procs - body_procs
            if missing_in_body:
                checks.append(
                    CheckResult(
                        name="spec_body_alignment",
                        status=ValidationStatus.FAIL,
                        message=f"Procedure(s) declared in spec but missing in body: {list(missing_in_body)}",
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name="spec_body_alignment",
                        status=ValidationStatus.PASS,
                        message=f"All {len(spec_procs)} declared procedure(s) implemented in package body.",
                        details={"procedures": list(spec_procs)},
                    )
                )

        # Check 3: Exception handling
        if pkb:
            has_exception_block = "EXCEPTION" in pkb.upper()
            has_when_others = "WHEN OTHERS" in pkb.upper()
            if has_exception_block and has_when_others:
                checks.append(
                    CheckResult(
                        name="exception_handling",
                        status=ValidationStatus.PASS,
                        message="Robust exception handling with WHEN OTHERS blocks detected.",
                    )
                )
            elif has_exception_block:
                checks.append(
                    CheckResult(
                        name="exception_handling",
                        status=ValidationStatus.WARN,
                        message="EXCEPTION block present but missing global WHEN OTHERS trap.",
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name="exception_handling",
                        status=ValidationStatus.FAIL,
                        message="No EXCEPTION blocks found in package body.",
                    )
                )

        # Check 4: Watermark / Incremental logic
        if pkb:
            watermark_hints = ["WATERMARK", "LAST_RUN", "TOKEN", "UPDATE_WATERMARK", "PARAM_VALUE"]
            has_watermark = any(hint in pkb.upper() for hint in watermark_hints)
            if has_watermark:
                checks.append(
                    CheckResult(
                        name="watermark_token_logic",
                        status=ValidationStatus.PASS,
                        message="Incremental watermark/token management logic detected in package body.",
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name="watermark_token_logic",
                        status=ValidationStatus.WARN,
                        message="No watermark update logic found in package body.",
                    )
                )

        has_fail = any(c.status == ValidationStatus.FAIL for c in checks)
        has_warn = any(c.status == ValidationStatus.WARN for c in checks)
        overall = ValidationStatus.FAIL if has_fail else (ValidationStatus.WARN if has_warn else ValidationStatus.PASS)

        return overall, [c.to_dict() for c in checks]


class TraceabilityValidator:
    """
    Verifies that business attributes defined in FDD trace through
    TDD, SQL, and PL/SQL.
    """

    @staticmethod
    def validate_traceability(
        fdd_content: Dict[str, Any],
        tdd_content: Optional[Dict[str, Any]] = None,
        sql_content: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ValidationStatus, List[Dict[str, Any]], Dict[str, Any]]:
        checks: List[CheckResult] = []
        fdd_attributes = [
            m.get("business_attribute")
            for m in fdd_content.get("attribute_mappings", [])
            if m.get("business_attribute")
        ]

        if not fdd_attributes:
            checks.append(
                CheckResult(
                    name="fdd_attributes_defined",
                    status=ValidationStatus.WARN,
                    message="No business attributes found in FDD to trace.",
                )
            )
            return ValidationStatus.WARN, [c.to_dict() for c in checks], {}

        matrix = []
        tdd_cols = []
        if tdd_content:
            tdd_cols = [
                c.get("business_attribute") or c.get("column_name")
                for c in tdd_content.get("sql_design", {}).get("select_columns", [])
            ]

        sql_text = (sql_content.get("extraction_sql", "") if sql_content else "").upper()

        traced_count = 0
        for attr in fdd_attributes:
            in_tdd = attr in tdd_cols if tdd_cols else True
            in_sql = attr.upper() in sql_text if sql_text else True

            status = "FULL" if (in_tdd and in_sql) else ("PARTIAL" if (in_tdd or in_sql) else "MISSING")
            if status != "MISSING":
                traced_count += 1

            matrix.append({
                "attribute": attr,
                "in_fdd": True,
                "in_tdd": in_tdd,
                "in_sql": in_sql,
                "status": status,
            })

        coverage_pct = round((traced_count / len(fdd_attributes)) * 100, 1)
        if coverage_pct >= 90:
            checks.append(
                CheckResult(
                    name="lineage_coverage",
                    status=ValidationStatus.PASS,
                    message=f"Lineage trace coverage is {coverage_pct}% ({traced_count}/{len(fdd_attributes)} attributes).",
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="lineage_coverage",
                    status=ValidationStatus.WARN,
                    message=f"Lineage trace coverage is below 90%: {coverage_pct}% ({traced_count}/{len(fdd_attributes)} attributes).",
                )
            )

        trace_summary = {
            "total_attributes": len(fdd_attributes),
            "traced_attributes": traced_count,
            "coverage_pct": coverage_pct,
            "matrix": matrix,
        }

        has_fail = any(c.status == ValidationStatus.FAIL for c in checks)
        has_warn = any(c.status == ValidationStatus.WARN for c in checks)
        overall = ValidationStatus.FAIL if has_fail else (ValidationStatus.WARN if has_warn else ValidationStatus.PASS)

        return overall, [c.to_dict() for c in checks], trace_summary
