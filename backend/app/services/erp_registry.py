"""Explicit seed loader for enterprise ERP profiles and demo projects."""

import json
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ERPProfile, ERPProfileVersion, PromptVersion, Project, ProjectStatus
from app.services.workflow import WorkflowEngine

SEED_ERP_DEFINITIONS = [
    {
        "key": "oracle-fusion-cloud",
        "name": "Oracle Fusion Cloud",
        "display_name": "Oracle Fusion Cloud",
        "vendor": "Oracle",
        "product_version": "Cloud",
        "description": "Production integration profile for Oracle Fusion Cloud ERP (Payables, Receivables, TCA).",
        "dialect": "Oracle",
        "adapters": {"SQL": "oracle_sql", "PKS": "oracle_plsql", "PKB": "oracle_plsql"},
        "traceability_adapter": "oracle_attribute_lineage",
        "sample_project": {
            "name": "Oracle Fusion AP Invoices & Lines Outbound Feed",
            "description": "Production integration package for AP Invoices & Lines with HZ_PARTIES supplier resolution and delta watermarking.",
            "business_requirement": "Extract AP Invoices and itemized Lines for active suppliers created or modified in the last 24 hours. Include Supplier Name from HZ_PARTIES via VENDOR_ID. Output CSV delimited by '|' and generate PL/SQL package for database staging.",
            "erp_schema_context": {
                "tables": [
                    {
                        "name": "AP_INVOICES_ALL",
                        "description": "Invoice header records in Oracle Fusion Payables",
                        "columns": [
                            {"name": "INVOICE_ID", "data_type": "NUMBER", "nullable": False, "primary_key": True},
                            {"name": "INVOICE_NUM", "data_type": "VARCHAR2(50)", "nullable": False},
                            {"name": "INVOICE_DATE", "data_type": "DATE", "nullable": False},
                            {"name": "INVOICE_AMOUNT", "data_type": "NUMBER", "nullable": False},
                            {"name": "PAYMENT_STATUS_FLAG", "data_type": "VARCHAR2(1)", "nullable": True},
                            {"name": "VENDOR_ID", "data_type": "NUMBER", "nullable": True, "foreign_key": "HZ_PARTIES.PARTY_ID"},
                            {"name": "CANCELLED_DATE", "data_type": "DATE", "nullable": True},
                            {"name": "LAST_UPDATE_DATE", "data_type": "TIMESTAMP", "nullable": False},
                        ],
                    },
                    {
                        "name": "AP_INVOICE_LINES_ALL",
                        "description": "Itemized lines for each invoice header",
                        "columns": [
                            {"name": "INVOICE_ID", "data_type": "NUMBER", "nullable": False, "foreign_key": "AP_INVOICES_ALL.INVOICE_ID"},
                            {"name": "LINE_NUMBER", "data_type": "NUMBER", "nullable": False, "primary_key": True},
                            {"name": "LINE_TYPE_LOOKUP_CODE", "data_type": "VARCHAR2(25)", "nullable": False},
                            {"name": "AMOUNT", "data_type": "NUMBER", "nullable": False},
                            {"name": "DESCRIPTION", "data_type": "VARCHAR2(240)", "nullable": True},
                            {"name": "LAST_UPDATE_DATE", "data_type": "TIMESTAMP", "nullable": False},
                        ],
                    },
                    {
                        "name": "HZ_PARTIES",
                        "description": "Trading Community Architecture (TCA) parties including vendors and suppliers",
                        "columns": [
                            {"name": "PARTY_ID", "data_type": "NUMBER", "nullable": False, "primary_key": True},
                            {"name": "PARTY_NAME", "data_type": "VARCHAR2(360)", "nullable": False},
                            {"name": "PARTY_NUMBER", "data_type": "VARCHAR2(30)", "nullable": True},
                        ],
                    },
                ],
                "foreign_keys": [
                    {"from": "AP_INVOICE_LINES_ALL.INVOICE_ID", "to": "AP_INVOICES_ALL.INVOICE_ID"},
                    {"from": "AP_INVOICES_ALL.VENDOR_ID", "to": "HZ_PARTIES.PARTY_ID"},
                ],
            }
        }
    },
    {
        "key": "sap-s4hana-cloud",
        "name": "SAP S/4HANA Cloud",
        "display_name": "SAP S/4HANA Cloud",
        "vendor": "SAP",
        "product_version": "2023 / Cloud",
        "description": "Enterprise integration profile for SAP S/4HANA (FI/CO, MM, SD, Business Partner).",
        "dialect": "HANA",
        "adapters": {"SQL": "generic_json", "PKS": "generic_json", "PKB": "generic_json"},
        "traceability_adapter": "generic_json",
        "sample_project": {
            "name": "SAP S/4HANA Accounts Payable Integration",
            "description": "Outbound extraction package for SAP BKPF/BSEG Accounting Documents with Business Partner LFA1 enrichment.",
            "business_requirement": "Extract Accounting Document Headers (BKPF) and Segment Items (BSEGK/BSEG) for vendor invoices. Join LFA1 to resolve Vendor Name. Output XML and SQL staging package.",
            "erp_schema_context": {
                "tables": [
                    {
                        "name": "BKPF",
                        "description": "Accounting Document Header in SAP S/4HANA",
                        "columns": [
                            {"name": "BELNR", "data_type": "NCHAR(10)", "nullable": False, "primary_key": True},
                            {"name": "BUKRS", "data_type": "NCHAR(4)", "nullable": False, "primary_key": True},
                            {"name": "GJAHR", "data_type": "NUMC(4)", "nullable": False, "primary_key": True},
                            {"name": "BLDAT", "data_type": "DATS", "nullable": False},
                            {"name": "LIFNR", "data_type": "NCHAR(10)", "nullable": True, "foreign_key": "LFA1.LIFNR"},
                        ],
                    },
                    {
                        "name": "BSEG",
                        "description": "Accounting Document Line Items in SAP S/4HANA",
                        "columns": [
                            {"name": "BELNR", "data_type": "NCHAR(10)", "nullable": False, "foreign_key": "BKPF.BELNR"},
                            {"name": "BUZEI", "data_type": "NUMC(3)", "nullable": False, "primary_key": True},
                            {"name": "WRBTR", "data_type": "CURR(13,2)", "nullable": False},
                            {"name": "SGTXT", "data_type": "CHAR(50)", "nullable": True},
                        ],
                    },
                    {
                        "name": "LFA1",
                        "description": "Vendor Master (General Section) in SAP",
                        "columns": [
                            {"name": "LIFNR", "data_type": "NCHAR(10)", "nullable": False, "primary_key": True},
                            {"name": "NAME1", "data_type": "CHAR(35)", "nullable": False},
                            {"name": "ORT01", "data_type": "CHAR(35)", "nullable": True},
                        ],
                    },
                ],
                "foreign_keys": [
                    {"from": "BSEG.BELNR", "to": "BKPF.BELNR"},
                    {"from": "BKPF.LIFNR", "to": "LFA1.LIFNR"},
                ],
            }
        }
    },
    {
        "key": "netsuite-erp",
        "name": "NetSuite ERP",
        "display_name": "NetSuite ERP",
        "vendor": "Oracle NetSuite",
        "product_version": "2024.1",
        "description": "Cloud ERP integration profile for Oracle NetSuite (Transactions, Customers, Invoices, Payments).",
        "dialect": "SuiteQL",
        "adapters": {"SQL": "generic_json", "PKS": "generic_json", "PKB": "generic_json"},
        "traceability_adapter": "generic_json",
        "sample_project": {
            "name": "NetSuite Customer Payment Sync",
            "description": "Bi-directional customer payment and invoice status synchronization feed for NetSuite.",
            "business_requirement": "Synchronize NetSuite Customer Payment transactions (transaction table) linked to Customer (entity) and TransactionLine items. Extract payment amounts, dates, and apply-to invoices.",
            "erp_schema_context": {
                "tables": [
                    {
                        "name": "Transaction",
                        "description": "NetSuite Transaction header table",
                        "columns": [
                            {"name": "id", "data_type": "INTEGER", "nullable": False, "primary_key": True},
                            {"name": "tranId", "data_type": "VARCHAR", "nullable": False},
                            {"name": "trandate", "data_type": "DATE", "nullable": False},
                            {"name": "entity", "data_type": "INTEGER", "nullable": False, "foreign_key": "Customer.id"},
                            {"name": "foreigntotal", "data_type": "FLOAT", "nullable": False},
                        ],
                    },
                    {
                        "name": "Customer",
                        "description": "NetSuite Customer entity table",
                        "columns": [
                            {"name": "id", "data_type": "INTEGER", "nullable": False, "primary_key": True},
                            {"name": "companyName", "data_type": "VARCHAR", "nullable": False},
                            {"name": "entityId", "data_type": "VARCHAR", "nullable": False},
                        ],
                    },
                ],
                "foreign_keys": [
                    {"from": "Transaction.entity", "to": "Customer.id"},
                ],
            }
        }
    },
    {
        "key": "workday-financials",
        "name": "Workday Financial Management",
        "display_name": "Workday Financial Management",
        "vendor": "Workday",
        "product_version": "2024R1",
        "description": "Enterprise cloud financial profile for Workday (General Ledger, Customer Accounts, Supplier Accounts).",
        "dialect": "Workday RaaS / SQL",
        "adapters": {"SQL": "generic_json", "PKS": "generic_json", "PKB": "generic_json"},
        "traceability_adapter": "generic_json",
        "sample_project": {
            "name": "Workday Financial Journal Import & Export",
            "description": "Automated ledger entry and journal line extraction integration for Workday Financials.",
            "business_requirement": "Extract Accounting Journal Lines from Workday General Ledger with Ledger Account, Cost Center, and Debit/Credit amounts for financial reconciliation.",
            "erp_schema_context": {
                "tables": [
                    {
                        "name": "Journal_Entry_Header",
                        "description": "Workday Accounting Journal Entry Header",
                        "columns": [
                            {"name": "Journal_Entry_ID", "data_type": "VARCHAR", "nullable": False, "primary_key": True},
                            {"name": "Company_ID", "data_type": "VARCHAR", "nullable": False},
                            {"name": "Accounting_Date", "data_type": "DATE", "nullable": False},
                        ],
                    },
                    {
                        "name": "Journal_Entry_Line",
                        "description": "Workday Accounting Journal Line Detail",
                        "columns": [
                            {"name": "Journal_Entry_ID", "data_type": "VARCHAR", "nullable": False, "foreign_key": "Journal_Entry_Header.Journal_Entry_ID"},
                            {"name": "Line_Number", "data_type": "INTEGER", "nullable": False, "primary_key": True},
                            {"name": "Ledger_Account", "data_type": "VARCHAR", "nullable": False},
                            {"name": "Debit_Amount", "data_type": "NUMERIC", "nullable": True},
                            {"name": "Credit_Amount", "data_type": "NUMERIC", "nullable": True},
                        ],
                    },
                ],
                "foreign_keys": [
                    {"from": "Journal_Entry_Line.Journal_Entry_ID", "to": "Journal_Entry_Header.Journal_Entry_ID"},
                ],
            }
        }
    },
    {
        "key": "dynamics-365-fo",
        "name": "Microsoft Dynamics 365 F&O",
        "display_name": "Microsoft Dynamics 365 F&O",
        "vendor": "Microsoft",
        "product_version": "10.0 / One Version",
        "description": "Integration profile for Microsoft Dynamics 365 Finance & Operations (VendTable, PurchTable, CustTable).",
        "dialect": "T-SQL / OData",
        "adapters": {"SQL": "generic_json", "PKS": "generic_json", "PKB": "generic_json"},
        "traceability_adapter": "generic_json",
        "sample_project": {
            "name": "Dynamics 365 Vendor Master Sync",
            "description": "Vendor master data and purchase order status synchronization feed for Dynamics 365 F&O.",
            "business_requirement": "Extract active Vendors from VendTable with associated Purchase Orders (PurchTable) and Line Items (PurchLine) for Procurement analysis.",
            "erp_schema_context": {
                "tables": [
                    {
                        "name": "VendTable",
                        "description": "Dynamics 365 Finance Vendor Master table",
                        "columns": [
                            {"name": "AccountNum", "data_type": "NVARCHAR(20)", "nullable": False, "primary_key": True},
                            {"name": "VendorName", "data_type": "NVARCHAR(100)", "nullable": False},
                            {"name": "DataAreaId", "data_type": "NVARCHAR(4)", "nullable": False},
                        ],
                    },
                    {
                        "name": "PurchTable",
                        "description": "Dynamics 365 Purchase Order Header",
                        "columns": [
                            {"name": "PurchId", "data_type": "NVARCHAR(20)", "nullable": False, "primary_key": True},
                            {"name": "OrderAccount", "data_type": "NVARCHAR(20)", "nullable": False, "foreign_key": "VendTable.AccountNum"},
                            {"name": "PurchStatus", "data_type": "INTEGER", "nullable": False},
                        ],
                    },
                ],
                "foreign_keys": [
                    {"from": "PurchTable.OrderAccount", "to": "VendTable.AccountNum"},
                ],
            }
        }
    }
]


async def ensure_seed_profiles(db: AsyncSession) -> ERPProfile:
    """Ensure all seed enterprise ERP profiles exist and are published."""
    first_profile = None

    for erp_def in SEED_ERP_DEFINITIONS:
        result = await db.execute(select(ERPProfile).where(ERPProfile.key == erp_def["key"]))
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = ERPProfile(
                key=erp_def["key"],
                name=erp_def["name"],
                display_name=erp_def["display_name"],
                vendor=erp_def["vendor"],
                product_version=erp_def["product_version"],
                description=erp_def["description"],
                active=True,
                status="PUBLISHED",
                created_by="seed",
                updated_by="seed",
                configuration={"dialect": erp_def["dialect"], "schema_grounding_required": True},
            )
            db.add(profile)
            await db.flush()

        if first_profile is None:
            first_profile = profile

        version_result = await db.execute(select(ERPProfileVersion).where(
            ERPProfileVersion.profile_id == profile.id, ERPProfileVersion.version == 1))
        profile_version = version_result.scalar_one_or_none()
        if profile_version is None:
            stages = [
                ("CONTEXT_ANALYSIS", [], "oracle_context_analysis" if erp_def["key"] == "oracle-fusion-cloud" else "generic_json", "CONTEXT_ANALYSIS"),
                ("FDD", ["CONTEXT_ANALYSIS"], "oracle_fdd" if erp_def["key"] == "oracle-fusion-cloud" else "generic_json", "FDD"),
                ("TDD", ["FDD"], "oracle_tdd" if erp_def["key"] == "oracle-fusion-cloud" else "generic_json", "TDD"),
                ("SQL", ["TDD"], erp_def["adapters"]["SQL"], "SQL"),
                ("PKS", ["SQL"], erp_def["adapters"]["PKS"], "CODE_GENERATION"),
                ("PKB", ["SQL"], erp_def["adapters"]["PKB"], "CODE_GENERATION"),
                ("DEPLOYMENT", ["PKS", "PKB"], "oracle_deployment" if erp_def["key"] == "oracle-fusion-cloud" else "generic_json", "DEPLOYMENT"),
            ]
            workflow_stages = [
                {"type": t, "depends_on": d, "adapter": a, "prompt_stage": ps, "label": t.replace("_", " ")}
                for t, d, a, ps in stages
            ]
            profile_version = ERPProfileVersion(
                profile_id=profile.id,
                version=1,
                status="PUBLISHED",
                supported_artifact_types=[x[0] for x in stages],
                configuration={
                    "workflow": {"stages": workflow_stages},
                    "generation": {"strategy": "configured_adapters"},
                    "validation": {
                        "schema_conformity": True,
                        "adapters": erp_def["adapters"],
                        "cross_artifact_traceability": True,
                        "traceability_adapter": erp_def["traceability_adapter"],
                    },
                },
                created_by="seed",
                updated_by="seed",
            )
            db.add(profile_version)
            await db.flush()

            # Seed stage prompts for Oracle profile
            if erp_def["key"] == "oracle-fusion-cloud":
                fixture_path = Path(__file__).resolve().parents[2] / "seed" / "oracle_fusion.prompts.json"
                if fixture_path.exists():
                    prompt_data = json.loads(fixture_path.read_text())
                    for stage, content in prompt_data.items():
                        res = await db.execute(select(PromptVersion.id).where(
                            PromptVersion.profile_version_id == profile_version.id,
                            PromptVersion.name == f"{stage} instructions", PromptVersion.version == 1))
                        if res.scalar_one_or_none() is None:
                            db.add(PromptVersion(
                                scope="STAGE", profile_version_id=profile_version.id, name=f"{stage} instructions",
                                stage=stage, content=content, version=1, status="PUBLISHED", variables=[],
                                created_by="seed", updated_by="seed",
                            ))

        profile.status = "PUBLISHED"
        profile.active = True
        await db.flush()

    # Seed sample projects for each ERP if database has 0 projects
    proj_count_res = await db.execute(select(func.count(Project.id)))
    if proj_count_res.scalar_one() == 0:
        for erp_def in SEED_ERP_DEFINITIONS:
            res = await db.execute(select(ERPProfile).where(ERPProfile.key == erp_def["key"]))
            p_obj = res.scalar_one_or_none()
            if not p_obj:
                continue
            ver_res = await db.execute(select(ERPProfileVersion).where(
                ERPProfileVersion.profile_id == p_obj.id, ERPProfileVersion.status == "PUBLISHED"
            ).order_by(ERPProfileVersion.version.desc()).limit(1))
            pv_obj = ver_res.scalar_one_or_none()
            if not pv_obj:
                continue

            sp_info = erp_def["sample_project"]
            project = Project(
                name=sp_info["name"],
                description=sp_info["description"],
                business_requirement=sp_info["business_requirement"],
                erp_schema_context=sp_info["erp_schema_context"],
                erp_profile_id=p_obj.id,
                erp_profile_version_id=pv_obj.id,
                status=ProjectStatus.ACTIVE,
            )
            db.add(project)
            await db.flush()

            workflow = WorkflowEngine(db)
            await workflow.initialize_project_artifacts(project)
            await db.flush()

    return first_profile
