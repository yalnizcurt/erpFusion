"""
erpFusion — Demo / Mock LLM Provider

Provides high-fidelity, deterministic enterprise Oracle ERP responses
for AP Invoice extraction when running in offline/demo mode or before
the user configures their GROQ_API_KEY.
"""

import json
import logging
from typing import Any, Dict

from app.services.llm.base import LLMProvider, LLMRequest, LLMResponse

logger = logging.getLogger("erpfusion.llm.mock")


class MockERPProvider(LLMProvider):
    """High-fidelity Oracle fixture plus data-driven responses for generic strategies."""

    async def generate_configured_json(self, request: LLMRequest) -> Dict[str, Any]:
        """Return a deterministic response grounded in arbitrary compiled profile context."""
        prefix = "Use the following versioned generation context as the source of truth. Do not infer unsupported ERP facts.\n\n"
        try:
            context = json.loads(request.user_prompt.removeprefix(prefix))
        except json.JSONDecodeError:
            context = {"current_task": request.user_prompt}
        profile = context.get("erp", {})
        entities = context.get("schema_context", {}).get("entities", [])
        tables = context.get("schema_context", {}).get("tables", [])
        return {
            "artifact_type": context.get("stage", ""),
            "erp_name": profile.get("name", ""),
            "erp_profile_version": profile.get("version"),
            "objective": context.get("requirement", ""),
            "source_entities": entities or tables,
            "implementation_guidance": request.system_prompt,
            "knowledge_references": [item.get("name") for item in context.get("knowledge", [])],
            "standard_packages_considered": [item.get("name") for item in context.get("standard_packages", [])],
            "reviewer_guidance": context.get("reviewer_guidance", []),
            "current_task": context.get("current_task", ""),
        }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        system_lower = request.system_prompt.lower()
        user_lower = request.user_prompt.lower()

        content: Dict[str, Any] = {}

        if "analyst" in system_lower:
            content = {
                "business_objective": "Extract approved and paid Accounts Payable invoices from Oracle Fusion ERP for downstream enterprise data warehouse ingestion and financial reconciliation.",
                "identified_entities": [
                    {
                        "business_name": "AP Invoices Header",
                        "erp_table": "AP_INVOICES_ALL",
                        "role": "primary",
                        "relevant_columns": [
                            {"column_name": "INVOICE_ID", "data_type": "NUMBER", "business_meaning": "Unique invoice identifier"},
                            {"column_name": "INVOICE_NUM", "data_type": "VARCHAR2(50)", "business_meaning": "Supplier invoice number"},
                            {"column_name": "INVOICE_DATE", "data_type": "DATE", "business_meaning": "Date on invoice"},
                            {"column_name": "INVOICE_AMOUNT", "data_type": "NUMBER", "business_meaning": "Total invoice header amount"},
                            {"column_name": "PAYMENT_STATUS_FLAG", "data_type": "VARCHAR2(1)", "business_meaning": "Y=Paid, N=Unpaid, P=Partially Paid"},
                            {"column_name": "VENDOR_ID", "data_type": "NUMBER", "business_meaning": "Supplier ID pointer to party"},
                            {"column_name": "LAST_UPDATE_DATE", "data_type": "TIMESTAMP", "business_meaning": "System audit timestamp for delta tracking"},
                        ],
                    },
                    {
                        "business_name": "AP Invoice Lines",
                        "erp_table": "AP_INVOICE_LINES_ALL",
                        "role": "child",
                        "relevant_columns": [
                            {"column_name": "INVOICE_ID", "data_type": "NUMBER", "business_meaning": "Foreign key to header"},
                            {"column_name": "LINE_NUMBER", "data_type": "NUMBER", "business_meaning": "Sequential line item number"},
                            {"column_name": "LINE_TYPE_LOOKUP_CODE", "data_type": "VARCHAR2(25)", "business_meaning": "ITEM, TAX, FREIGHT, MISCELLANEOUS"},
                            {"column_name": "AMOUNT", "data_type": "NUMBER", "business_meaning": "Line item amount"},
                            {"column_name": "DESCRIPTION", "data_type": "VARCHAR2(240)", "business_meaning": "Item/service description"},
                        ],
                    },
                    {
                        "business_name": "Supplier Party",
                        "erp_table": "HZ_PARTIES",
                        "role": "lookup",
                        "relevant_columns": [
                            {"column_name": "PARTY_ID", "data_type": "NUMBER", "business_meaning": "Trading community party identifier"},
                            {"column_name": "PARTY_NAME", "data_type": "VARCHAR2(360)", "business_meaning": "Legal business name of supplier"},
                            {"column_name": "PARTY_NUMBER", "data_type": "VARCHAR2(30)", "business_meaning": "Registry supplier identification number"},
                        ],
                    },
                ],
                "relationships": [
                    {
                        "from_entity": "AP_INVOICES_ALL",
                        "to_entity": "AP_INVOICE_LINES_ALL",
                        "join_type": "INNER",
                        "join_condition": "AP_INVOICES_ALL.INVOICE_ID = AP_INVOICE_LINES_ALL.INVOICE_ID",
                        "source_evidence": "Foreign key FK_AP_INV_LINES_INV_ID",
                    },
                    {
                        "from_entity": "AP_INVOICES_ALL",
                        "to_entity": "HZ_PARTIES",
                        "join_type": "LEFT OUTER",
                        "join_condition": "AP_INVOICES_ALL.VENDOR_ID = HZ_PARTIES.PARTY_ID",
                        "source_evidence": "Oracle TCA Party ID link",
                    },
                ],
                "extraction_modes": ["FULL", "DELTA", "SELECTIVE"],
                "required_filters": [
                    {
                        "description": "Exclude cancelled and draft invoices",
                        "filter_expression": "NVL(AP_INVOICES_ALL.CANCELLED_DATE, NULL) IS NULL",
                    }
                ],
                "required_transformations": [
                    {
                        "attribute": "PARTY_NAME",
                        "transformation": "REPLACE(REPLACE(PARTY_NAME, '|', ' '), CHR(10), ' ')",
                        "reason": "Prevent pipe delimiter collision and newline truncation in pipe-delimited extracts",
                    }
                ],
                "output_expectations": {
                    "format": "DELIMITED_FLAT_FILE",
                    "delimiter": "|",
                    "estimated_columns": 12,
                },
                "assumptions": [
                    {
                        "description": "Only validated or paid AP invoices are required for this extraction scope.",
                        "impact": "Unapproved draft invoices will be excluded from extracts.",
                        "needs_confirmation": False,
                    }
                ],
                "ambiguities": [],
                "missing_information": [],
                "confidence_notes": [
                    "All referenced tables and columns are standard Oracle Fusion Cloud Payables schema objects."
                ],
            }

        elif "functional design document" in system_lower:
            content = {
                "document_title": "FDD: Oracle Fusion AP Invoices & Lines Outbound Extraction",
                "business_scope": {
                    "purpose": "Provide automated outbound extraction of AP Invoice Headers, Lines, and Supplier data for enterprise reporting and audit compliance.",
                    "scope": "All approved invoices with non-cancelled status across primary operating units.",
                    "relevant_entities": ["AP Invoices", "AP Invoice Lines", "Suppliers"],
                    "downstream_use": "Corporate Financial Reporting & Snowflake Data Lake",
                },
                "attribute_mappings": [
                    {"seq": 1, "business_attribute": "Invoice ID", "source_entity": "AP Invoices Header", "source_table": "AP_INVOICES_ALL", "source_column": "INVOICE_ID", "data_type": "NUMBER", "business_description": "Unique identifier", "transformation": None, "business_rule": None, "nullable": False, "in_output": True},
                    {"seq": 2, "business_attribute": "Invoice Number", "source_entity": "AP Invoices Header", "source_table": "AP_INVOICES_ALL", "source_column": "INVOICE_NUM", "data_type": "VARCHAR2", "business_description": "Supplier invoice ref", "transformation": "REPLACE(INVOICE_NUM, '|', ' ')", "business_rule": None, "nullable": False, "in_output": True},
                    {"seq": 3, "business_attribute": "Invoice Date", "source_entity": "AP Invoices Header", "source_table": "AP_INVOICES_ALL", "source_column": "INVOICE_DATE", "data_type": "DATE", "business_description": "Invoice accounting date", "transformation": "TO_CHAR(INVOICE_DATE, 'YYYY-MM-DD')", "business_rule": None, "nullable": False, "in_output": True},
                    {"seq": 4, "business_attribute": "Total Amount", "source_entity": "AP Invoices Header", "source_table": "AP_INVOICES_ALL", "source_column": "INVOICE_AMOUNT", "data_type": "NUMBER", "business_description": "Invoice gross amount", "transformation": "TO_CHAR(INVOICE_AMOUNT, '999999990.00')", "business_rule": None, "nullable": False, "in_output": True},
                    {"seq": 5, "business_attribute": "Supplier Name", "source_entity": "Supplier Party", "source_table": "HZ_PARTIES", "source_column": "PARTY_NAME", "data_type": "VARCHAR2", "business_description": "Legal vendor name", "transformation": "REPLACE(REPLACE(PARTY_NAME, '|', ' '), CHR(10), ' ')", "business_rule": None, "nullable": True, "in_output": True},
                    {"seq": 6, "business_attribute": "Line Number", "source_entity": "AP Invoice Lines", "source_table": "AP_INVOICE_LINES_ALL", "source_column": "LINE_NUMBER", "data_type": "NUMBER", "business_description": "Sequential line position", "transformation": None, "business_rule": None, "nullable": False, "in_output": True},
                    {"seq": 7, "business_attribute": "Line Amount", "source_entity": "AP Invoice Lines", "source_table": "AP_INVOICE_LINES_ALL", "source_column": "AMOUNT", "data_type": "NUMBER", "business_description": "Itemized line amount", "transformation": "TO_CHAR(AMOUNT, '999999990.00')", "business_rule": None, "nullable": False, "in_output": True},
                    {"seq": 8, "business_attribute": "Line Description", "source_entity": "AP Invoice Lines", "source_table": "AP_INVOICE_LINES_ALL", "source_column": "DESCRIPTION", "data_type": "VARCHAR2", "business_description": "Line description", "transformation": "REPLACE(REPLACE(DESCRIPTION, '|', ' '), CHR(10), ' ')", "business_rule": None, "nullable": True, "in_output": True},
                ],
                "extraction_modes": {
                    "full": {"description": "Extract all historical active invoices", "filter_criteria": "AP_INVOICES_ALL.CANCELLED_DATE IS NULL"},
                    "delta": {"description": "Incremental run extracting records updated since last execution", "timestamp_column": "LAST_UPDATE_DATE", "filter_criteria": "AP_INVOICES_ALL.LAST_UPDATE_DATE >= :p_last_run_date"},
                    "selective": {"description": "Parameter-driven extraction by date window or supplier", "parameters": [":p_start_date", ":p_end_date", ":p_vendor_id"]},
                },
                "business_rules": [
                    {"rule_id": "BR001", "description": "Exclude cancelled invoices from outbound feed", "applies_to": ["Invoice ID"], "logic": "CANCELLED_DATE IS NULL"},
                    {"rule_id": "BR002", "description": "Sanitize pipe characters and carriage returns", "applies_to": ["Supplier Name", "Line Description", "Invoice Number"], "logic": "REPLACE with single space"},
                ],
                "sanitization_rules": {
                    "delimiter_character": "|",
                    "rules": [
                        {"rule_id": "SR001", "description": "Strip delimiter collision", "characters_handled": ["|"], "replacement": " ", "applies_to": "ALL_TEXT_FIELDS"},
                        {"rule_id": "SR002", "description": "Strip newline and carriage returns", "characters_handled": ["\n", "\r"], "replacement": " ", "applies_to": "ALL_TEXT_FIELDS"},
                    ],
                },
                "output_specification": {
                    "format": "DELIMITED_FLAT_FILE",
                    "delimiter": "|",
                    "header_row": True,
                    "file_naming": "AP_INVOICES_EXTRACT_YYYYMMDD_HH24MISS.dat",
                    "encoding": "UTF-8",
                    "null_representation": "",
                    "date_format": "YYYY-MM-DD",
                    "number_format": "999999990.00",
                },
            }

        elif "technical design document" in system_lower:
            content = {
                "document_title": "TDD: Oracle PL/SQL Extraction Engine for AP Invoices",
                "technical_architecture": {
                    "package_name": "XX_AP_INVOICES_EXTRACT_PKG",
                    "schema_owner": "FUSION_RUNTIME",
                    "description": "PL/SQL package providing cursor-driven UTL_FILE extraction with watermark token tracking.",
                },
                "source_entities": [
                    {"table_name": "AP_INVOICES_ALL", "alias": "inv", "role": "primary", "key_columns": ["INVOICE_ID"]},
                    {"table_name": "AP_INVOICE_LINES_ALL", "alias": "line", "role": "child", "key_columns": ["INVOICE_ID", "LINE_NUMBER"]},
                    {"table_name": "HZ_PARTIES", "alias": "pty", "role": "lookup", "key_columns": ["PARTY_ID"]},
                ],
                "entity_relationships": [
                    {"from_table": "AP_INVOICES_ALL", "from_alias": "inv", "to_table": "AP_INVOICE_LINES_ALL", "to_alias": "line", "join_type": "INNER JOIN", "join_condition": "inv.INVOICE_ID = line.INVOICE_ID", "purpose": "Retrieve line items per invoice"},
                    {"from_table": "AP_INVOICES_ALL", "from_alias": "inv", "to_table": "HZ_PARTIES", "to_alias": "pty", "join_type": "LEFT OUTER JOIN", "join_condition": "inv.VENDOR_ID = pty.PARTY_ID", "purpose": "Resolve supplier legal trading name"},
                ],
                "sql_design": {
                    "select_columns": [
                        {"source_table": "AP_INVOICES_ALL", "column_name": "INVOICE_ID", "alias": "invoice_id", "business_attribute": "Invoice ID"},
                        {"source_table": "AP_INVOICES_ALL", "column_name": "INVOICE_NUM", "alias": "invoice_number", "business_attribute": "Invoice Number"},
                        {"source_table": "AP_INVOICES_ALL", "column_name": "INVOICE_DATE", "alias": "invoice_date", "business_attribute": "Invoice Date"},
                        {"source_table": "AP_INVOICES_ALL", "column_name": "INVOICE_AMOUNT", "alias": "total_amount", "business_attribute": "Total Amount"},
                        {"source_table": "HZ_PARTIES", "column_name": "PARTY_NAME", "alias": "supplier_name", "business_attribute": "Supplier Name"},
                        {"source_table": "AP_INVOICE_LINES_ALL", "column_name": "LINE_NUMBER", "alias": "line_number", "business_attribute": "Line Number"},
                        {"source_table": "AP_INVOICE_LINES_ALL", "column_name": "AMOUNT", "alias": "line_amount", "business_attribute": "Line Amount"},
                        {"source_table": "AP_INVOICE_LINES_ALL", "column_name": "DESCRIPTION", "alias": "line_description", "business_attribute": "Line Description"},
                    ]
                },
                "watermark_strategy": {
                    "tracking_table": "XX_INTEGRATION_WATERMARKS",
                    "watermark_column": "inv.LAST_UPDATE_DATE",
                    "advancement_condition": "On successful file flush and close only",
                },
            }

        elif "generating an extraction query" in system_lower:
            content = {
                "extraction_sql": """SELECT 
    inv.INVOICE_ID,
    REPLACE(REPLACE(inv.INVOICE_NUM, '|', ' '), CHR(10), ' ') AS INVOICE_NUMBER,
    TO_CHAR(inv.INVOICE_DATE, 'YYYY-MM-DD') AS INVOICE_DATE,
    TO_CHAR(inv.INVOICE_AMOUNT, '999999990.00') AS TOTAL_AMOUNT,
    REPLACE(REPLACE(NVL(pty.PARTY_NAME, 'UNKNOWN'), '|', ' '), CHR(10), ' ') AS SUPPLIER_NAME,
    line.LINE_NUMBER,
    TO_CHAR(line.AMOUNT, '999999990.00') AS LINE_AMOUNT,
    REPLACE(REPLACE(NVL(line.DESCRIPTION, ''), '|', ' '), CHR(10), ' ') AS LINE_DESCRIPTION
FROM AP_INVOICES_ALL inv
INNER JOIN AP_INVOICE_LINES_ALL line ON inv.INVOICE_ID = line.INVOICE_ID
LEFT OUTER JOIN HZ_PARTIES pty ON inv.VENDOR_ID = pty.PARTY_ID
WHERE inv.CANCELLED_DATE IS NULL
  AND (:p_mode = 'FULL' OR inv.LAST_UPDATE_DATE >= :p_last_run_date)
ORDER BY inv.INVOICE_ID, line.LINE_NUMBER""",
                "full_mode_sql": """SELECT 
    inv.INVOICE_ID,
    REPLACE(REPLACE(inv.INVOICE_NUM, '|', ' '), CHR(10), ' ') AS INVOICE_NUMBER,
    TO_CHAR(inv.INVOICE_DATE, 'YYYY-MM-DD') AS INVOICE_DATE,
    TO_CHAR(inv.INVOICE_AMOUNT, '999999990.00') AS TOTAL_AMOUNT,
    REPLACE(REPLACE(NVL(pty.PARTY_NAME, 'UNKNOWN'), '|', ' '), CHR(10), ' ') AS SUPPLIER_NAME,
    line.LINE_NUMBER,
    TO_CHAR(line.AMOUNT, '999999990.00') AS LINE_AMOUNT,
    REPLACE(REPLACE(NVL(line.DESCRIPTION, ''), '|', ' '), CHR(10), ' ') AS LINE_DESCRIPTION
FROM AP_INVOICES_ALL inv
INNER JOIN AP_INVOICE_LINES_ALL line ON inv.INVOICE_ID = line.INVOICE_ID
LEFT OUTER JOIN HZ_PARTIES pty ON inv.VENDOR_ID = pty.PARTY_ID
WHERE inv.CANCELLED_DATE IS NULL
ORDER BY inv.INVOICE_ID, line.LINE_NUMBER""",
                "delta_mode_sql": """SELECT 
    inv.INVOICE_ID,
    REPLACE(REPLACE(inv.INVOICE_NUM, '|', ' '), CHR(10), ' ') AS INVOICE_NUMBER,
    TO_CHAR(inv.INVOICE_DATE, 'YYYY-MM-DD') AS INVOICE_DATE,
    TO_CHAR(inv.INVOICE_AMOUNT, '999999990.00') AS TOTAL_AMOUNT,
    REPLACE(REPLACE(NVL(pty.PARTY_NAME, 'UNKNOWN'), '|', ' '), CHR(10), ' ') AS SUPPLIER_NAME,
    line.LINE_NUMBER,
    TO_CHAR(line.AMOUNT, '999999990.00') AS LINE_AMOUNT,
    REPLACE(REPLACE(NVL(line.DESCRIPTION, ''), '|', ' '), CHR(10), ' ') AS LINE_DESCRIPTION
FROM AP_INVOICES_ALL inv
INNER JOIN AP_INVOICE_LINES_ALL line ON inv.INVOICE_ID = line.INVOICE_ID
LEFT OUTER JOIN HZ_PARTIES pty ON inv.VENDOR_ID = pty.PARTY_ID
WHERE inv.CANCELLED_DATE IS NULL
  AND inv.LAST_UPDATE_DATE >= :p_last_run_date
ORDER BY inv.INVOICE_ID, line.LINE_NUMBER""",
                "column_count": 8,
                "join_count": 2,
                "explanation": "Extracts AP invoices and lines with delimiter and newline sanitization, joining HZ_PARTIES for vendor identification.",
                "bind_variables": [
                    {"name": ":p_mode", "data_type": "VARCHAR2", "used_in": "BOTH"},
                    {"name": ":p_last_run_date", "data_type": "TIMESTAMP", "used_in": "DELTA"},
                ],
                "sanitized_columns": ["INVOICE_NUM", "SUPPLIER_NAME", "LINE_DESCRIPTION"],
            }

        elif "extraction package" in system_lower:
            pks = """CREATE OR REPLACE PACKAGE XX_AP_INVOICES_EXTRACT_PKG AS
  /******************************************************************************
   * Package: XX_AP_INVOICES_EXTRACT_PKG
   * Purpose: Enterprise extraction engine for Oracle Fusion AP Invoices
   * Author:  erpFusion Integration Engineering Agent
   ******************************************************************************/

  -- Main extraction procedure
  PROCEDURE run_extraction(
    p_mode           IN VARCHAR2 DEFAULT 'DELTA', -- FULL or DELTA
    p_directory      IN VARCHAR2 DEFAULT 'XX_OUTBOUND_DIR',
    p_file_name      IN VARCHAR2 DEFAULT NULL,
    p_record_count   OUT NUMBER,
    p_status         OUT VARCHAR2,
    p_err_msg        OUT VARCHAR2
  );

  -- Watermark advance procedure
  PROCEDURE update_watermark(
    p_integration_name IN VARCHAR2,
    p_new_watermark    IN TIMESTAMP
  );

END XX_AP_INVOICES_EXTRACT_PKG;
/"""

            pkb = """CREATE OR REPLACE PACKAGE BODY XX_AP_INVOICES_EXTRACT_PKG AS
  /******************************************************************************
   * Package Body: XX_AP_INVOICES_EXTRACT_PKG
   * Description:  Implements cursor-driven UTL_FILE extract with delta watermarking.
   ******************************************************************************/

  c_integration_name CONSTANT VARCHAR2(50) := 'AP_INVOICES_OUTBOUND';
  c_delimiter        CONSTANT VARCHAR2(1)  := '|';

  PROCEDURE run_extraction(
    p_mode           IN VARCHAR2 DEFAULT 'DELTA',
    p_directory      IN VARCHAR2 DEFAULT 'XX_OUTBOUND_DIR',
    p_file_name      IN VARCHAR2 DEFAULT NULL,
    p_record_count   OUT NUMBER,
    p_status         OUT VARCHAR2,
    p_err_msg        OUT VARCHAR2
  ) IS
    l_file_handle    UTL_FILE.FILE_TYPE;
    l_file_name      VARCHAR2(150);
    l_last_watermark TIMESTAMP;
    l_max_watermark  TIMESTAMP := SYSTIMESTAMP;
    l_count          NUMBER := 0;
    l_line_buffer    VARCHAR2(4000);

    CURSOR c_extract(cp_mode VARCHAR2, cp_watermark TIMESTAMP) IS
      SELECT 
        inv.INVOICE_ID,
        REPLACE(REPLACE(inv.INVOICE_NUM, '|', ' '), CHR(10), ' ') AS inv_num,
        TO_CHAR(inv.INVOICE_DATE, 'YYYY-MM-DD') AS inv_date,
        TO_CHAR(inv.INVOICE_AMOUNT, '999999990.00') AS tot_amt,
        REPLACE(REPLACE(NVL(pty.PARTY_NAME, 'UNKNOWN'), '|', ' '), CHR(10), ' ') AS supp_name,
        line.LINE_NUMBER,
        TO_CHAR(line.AMOUNT, '999999990.00') AS line_amt,
        REPLACE(REPLACE(NVL(line.DESCRIPTION, ''), '|', ' '), CHR(10), ' ') AS line_desc,
        inv.LAST_UPDATE_DATE
      FROM AP_INVOICES_ALL inv
      INNER JOIN AP_INVOICE_LINES_ALL line ON inv.INVOICE_ID = line.INVOICE_ID
      LEFT OUTER JOIN HZ_PARTIES pty ON inv.VENDOR_ID = pty.PARTY_ID
      WHERE inv.CANCELLED_DATE IS NULL
        AND (cp_mode = 'FULL' OR inv.LAST_UPDATE_DATE >= cp_watermark)
      ORDER BY inv.INVOICE_ID, line.LINE_NUMBER;

  BEGIN
    p_record_count := 0;
    p_status := 'SUCCESS';
    p_err_msg := NULL;

    -- Resolve file name
    IF p_file_name IS NULL THEN
      l_file_name := 'AP_INVOICES_' || TO_CHAR(SYSDATE, 'YYYYMMDD_HH24MISS') || '.dat';
    ELSE
      l_file_name := p_file_name;
    END IF;

    -- Resolve watermark
    IF UPPER(p_mode) = 'DELTA' THEN
      BEGIN
        SELECT LAST_WATERMARK_DATE INTO l_last_watermark
        FROM XX_INTEGRATION_WATERMARKS
        WHERE INTEGRATION_NAME = c_integration_name;
      EXCEPTION
        WHEN NO_DATA_FOUND THEN
          l_last_watermark := TO_TIMESTAMP('1970-01-01 00:00:00', 'YYYY-MM-DD HH24:MI:SS');
      END;
    ELSE
      l_last_watermark := TO_TIMESTAMP('1970-01-01 00:00:00', 'YYYY-MM-DD HH24:MI:SS');
    END IF;

    -- Open output file
    l_file_handle := UTL_FILE.FOPEN(p_directory, l_file_name, 'W', 32767);

    -- Write pipe-delimited header record
    l_line_buffer := 'INVOICE_ID|INVOICE_NUMBER|INVOICE_DATE|TOTAL_AMOUNT|SUPPLIER_NAME|LINE_NUMBER|LINE_AMOUNT|LINE_DESCRIPTION';
    UTL_FILE.PUT_LINE(l_file_handle, l_line_buffer);

    -- Loop records
    FOR r IN c_extract(UPPER(p_mode), l_last_watermark) LOOP
      l_line_buffer := r.INVOICE_ID || c_delimiter ||
                       r.inv_num || c_delimiter ||
                       r.inv_date || c_delimiter ||
                       r.tot_amt || c_delimiter ||
                       r.supp_name || c_delimiter ||
                       r.LINE_NUMBER || c_delimiter ||
                       r.line_amt || c_delimiter ||
                       r.line_desc;

      UTL_FILE.PUT_LINE(l_file_handle, l_line_buffer);
      l_count := l_count + 1;

      IF r.LAST_UPDATE_DATE > l_max_watermark THEN
        l_max_watermark := r.LAST_UPDATE_DATE;
      END IF;
    END LOOP;

    -- Close file and commit watermark
    UTL_FILE.FCLOSE(l_file_handle);
    p_record_count := l_count;

    -- Only advance watermark after successful file completion
    update_watermark(c_integration_name, l_max_watermark);

  EXCEPTION
    WHEN UTL_FILE.INVALID_PATH THEN
      IF UTL_FILE.IS_OPEN(l_file_handle) THEN UTL_FILE.FCLOSE(l_file_handle); END IF;
      p_status := 'FAILED';
      p_err_msg := 'Invalid directory path: ' || p_directory;
    WHEN OTHERS THEN
      IF UTL_FILE.IS_OPEN(l_file_handle) THEN UTL_FILE.FCLOSE(l_file_handle); END IF;
      p_status := 'FAILED';
      p_err_msg := 'SQLERRM: ' || SQLERRM;
  END run_extraction;

  PROCEDURE update_watermark(
    p_integration_name IN VARCHAR2,
    p_new_watermark    IN TIMESTAMP
  ) IS
  BEGIN
    MERGE INTO XX_INTEGRATION_WATERMARKS w
    USING DUAL ON (w.INTEGRATION_NAME = p_integration_name)
    WHEN MATCHED THEN
      UPDATE SET w.LAST_WATERMARK_DATE = p_new_watermark, w.LAST_RUN_DATE = SYSTIMESTAMP
    WHEN NOT MATCHED THEN
      INSERT (INTEGRATION_NAME, LAST_WATERMARK_DATE, LAST_RUN_DATE)
      VALUES (p_integration_name, p_new_watermark, SYSTIMESTAMP);
    COMMIT;
  EXCEPTION
    WHEN OTHERS THEN
      ROLLBACK;
      RAISE;
  END update_watermark;

END XX_AP_INVOICES_EXTRACT_PKG;
/"""

            content = {
                "package_name": "XX_AP_INVOICES_EXTRACT_PKG",
                "pks_content": pks,
                "pkb_content": pkb,
                "procedures": [
                    {"name": "run_extraction", "visibility": "PUBLIC", "description": "Extracts AP Invoices via UTL_FILE in FULL or DELTA mode", "parameters": ["p_mode", "p_directory", "p_file_name", "p_record_count", "p_status", "p_err_msg"]},
                    {"name": "update_watermark", "visibility": "PUBLIC", "description": "Updates high-water mark timestamp upon successful extract", "parameters": ["p_integration_name", "p_new_watermark"]},
                ],
                "features_implemented": {
                    "extraction_modes": ["FULL", "DELTA"],
                    "sanitization": True,
                    "watermark_management": True,
                    "file_generation": True,
                    "error_handling": True,
                    "logging": True,
                    "header_record": True,
                },
                "compilation_notes": [
                    "Requires READ, WRITE permissions on Oracle directory object XX_OUTBOUND_DIR.",
                    "Requires table XX_INTEGRATION_WATERMARKS for delta state management.",
                ],
            }

        else:
            # Default / Deployment
            content = {
                "package_name": "XX_AP_INVOICES_EXTRACT_PKG_DEPLOYMENT",
                "version": "1.0.0",
                "target_environment": "Oracle Fusion Cloud (ERP / Financials)",
                "prerequisites": [
                    {"check": "Directory object access", "verification_query": "SELECT * FROM all_directories WHERE directory_name = 'XX_OUTBOUND_DIR';"},
                    {"check": "Watermark table presence", "verification_query": "SELECT table_name FROM user_tables WHERE table_name = 'XX_INTEGRATION_WATERMARKS';"},
                ],
                "installation_steps": [
                    {"step_number": 1, "name": "Create Watermark Table", "file_or_action": "01_create_watermark_table.sql", "description": "State tracking table for incremental watermarks", "command": "@01_create_watermark_table.sql"},
                    {"step_number": 2, "name": "Compile Package Specification", "file_or_action": "XX_AP_INVOICES_EXTRACT_PKG.pks", "description": "PL/SQL package header declaration", "command": "@XX_AP_INVOICES_EXTRACT_PKG.pks"},
                    {"step_number": 3, "name": "Compile Package Body", "file_or_action": "XX_AP_INVOICES_EXTRACT_PKG.pkb", "description": "PL/SQL extraction implementation", "command": "@XX_AP_INVOICES_EXTRACT_PKG.pkb"},
                    {"step_number": 4, "name": "Grants and Synonyms", "file_or_action": "04_grants_and_synonyms.sql", "description": "Grant execute privileges to integration service account", "command": "@04_grants_and_synonyms.sql"},
                ],
                "grants_and_synonyms_sql": """GRANT EXECUTE ON XX_AP_INVOICES_EXTRACT_PKG TO FUSION_INTEGRATION_ROLE;
CREATE OR REPLACE SYNONYM APPS.XX_AP_INVOICES_EXTRACT_PKG FOR FUSION_RUNTIME.XX_AP_INVOICES_EXTRACT_PKG;""",
                "verification_script_sql": """SELECT status FROM user_objects WHERE object_name = 'XX_AP_INVOICES_EXTRACT_PKG';
-- Test invocation dry run:
DECLARE
  l_cnt NUMBER;
  l_st  VARCHAR2(20);
  l_err VARCHAR2(2000);
BEGIN
  XX_AP_INVOICES_EXTRACT_PKG.run_extraction(p_mode => 'DELTA', p_record_count => l_cnt, p_status => l_st, p_err_msg => l_err);
  DBMS_OUTPUT.PUT_LINE('Status: ' || l_st || ' | Records: ' || l_cnt);
END;
/""",
                "rollback_script_sql": """DROP PACKAGE BODY XX_AP_INVOICES_EXTRACT_PKG;
DROP PACKAGE XX_AP_INVOICES_EXTRACT_PKG;
DROP SYNONYM APPS.XX_AP_INVOICES_EXTRACT_PKG;""",
                "run_instructions_markdown": """### Deployment Runbook: XX_AP_INVOICES_EXTRACT_PKG
1. Connect via SQL*Plus or SQLcl as `FUSION_RUNTIME`
2. Run `@01_create_watermark_table.sql`
3. Compile spec: `@XX_AP_INVOICES_EXTRACT_PKG.pks`
4. Compile body: `@XX_AP_INVOICES_EXTRACT_PKG.pkb`
5. Verify package status is `VALID`
6. Apply grants and synonyms with `@04_grants_and_synonyms.sql`
7. Execute dry-run test block.""",
            }

        return LLMResponse(
            content=json.dumps(content, indent=2),
            model="openai/gpt-oss-120b (simulated/demo)",
            usage={"input_tokens": 120, "output_tokens": 850},
            raw_response={"mock": True},
        )
