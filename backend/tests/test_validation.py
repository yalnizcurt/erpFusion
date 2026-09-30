"""
erpFusion — Validation Engine Unit Tests
"""

import pytest
from app.models.base import ValidationStatus
from app.services.validation.engine import (
    PLSQLValidator,
    SQLValidator,
    SchemaConformityValidator,
    TraceabilityValidator,
)

SAMPLE_SCHEMA = {
    "tables": [
        {
            "name": "AP_INVOICES_ALL",
            "columns": [{"name": "INVOICE_ID"}, {"name": "INVOICE_NUM"}, {"name": "LAST_UPDATE_DATE"}],
        },
        {
            "name": "AP_INVOICE_LINES_ALL",
            "columns": [{"name": "INVOICE_ID"}, {"name": "LINE_NUMBER"}, {"name": "AMOUNT"}],
        },
    ]
}


def test_schema_conformity_pass():
    content = {
        "identified_entities": [
            {
                "erp_table": "AP_INVOICES_ALL",
                "relevant_columns": [{"column_name": "INVOICE_ID"}, {"column_name": "INVOICE_NUM"}],
            }
        ]
    }
    status, checks = SchemaConformityValidator.validate("CONTEXT_ANALYSIS", content, SAMPLE_SCHEMA)
    assert status == ValidationStatus.PASS
    assert any(c["status"] == "PASS" for c in checks)


def test_schema_conformity_flags_hallucinated_table():
    content = {
        "identified_entities": [
            {
                "erp_table": "NON_EXISTENT_TABLE_HALLUCINATED",
                "relevant_columns": [{"column_name": "SOME_COL"}],
            }
        ]
    }
    status, checks = SchemaConformityValidator.validate("CONTEXT_ANALYSIS", content, SAMPLE_SCHEMA)
    assert status == ValidationStatus.FAIL
    fail_check = next(c for c in checks if c["name"] == "table_existence_check")
    assert "NON_EXISTENT_TABLE_HALLUCINATED" in fail_check["details"]["hallucinated_tables"]


def test_sql_validator_detects_dangerous_statements():
    content = {"extraction_sql": "DROP TABLE AP_INVOICES_ALL; SELECT 1 FROM DUAL;"}
    status, checks = SQLValidator.validate(content)
    assert status == ValidationStatus.FAIL
    safety_check = next(c for c in checks if c["name"] == "read_only_safety")
    assert safety_check["status"] == "FAIL"


def test_sql_validator_passes_read_only_with_sanitization():
    content = {
        "extraction_sql": (
            "SELECT inv.INVOICE_ID, REPLACE(inv.INVOICE_NUM, '|', ' ') "
            "FROM AP_INVOICES_ALL inv WHERE inv.LAST_UPDATE_DATE >= :p_last_run"
        )
    }
    status, checks = SQLValidator.validate(content)
    assert status == ValidationStatus.PASS


def test_plsql_validator_detects_spec_body_mismatch():
    content = {
        "pks_content": "PACKAGE test_pkg AS PROCEDURE proc_one; PROCEDURE proc_two; END;",
        "pkb_content": "PACKAGE BODY test_pkg AS PROCEDURE proc_one IS BEGIN NULL; END; END;",
    }
    status, checks = PLSQLValidator.validate(content)
    assert status == ValidationStatus.FAIL
    align_check = next(c for c in checks if c["name"] == "spec_body_alignment")
    assert align_check["status"] == "FAIL"


def test_traceability_matrix_computation():
    fdd_content = {
        "attribute_mappings": [
            {"business_attribute": "Invoice ID"},
            {"business_attribute": "Invoice Number"},
            {"business_attribute": "Gross Amount"},
        ]
    }
    tdd_content = {
        "sql_design": {
            "select_columns": [
                {"business_attribute": "Invoice ID"},
                {"business_attribute": "Invoice Number"},
            ]
        }
    }
    sql_content = {
        "extraction_sql": "SELECT inv.INVOICE_ID, inv.INVOICE_NUM FROM AP_INVOICES_ALL"
    }

    status, checks, summary = TraceabilityValidator.validate_traceability(fdd_content, tdd_content, sql_content)
    assert summary["total_attributes"] == 3
    assert len(summary["matrix"]) == 3
