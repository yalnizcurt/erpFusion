"""Capability contracts and deterministic assertions shared by installed adapters."""

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

ADAPTER_VERSION = "1.0"
SCENARIOS = (
    "SUCCESS",
    "AUTHENTICATION_FAILED",
    "PERMISSION_DENIED",
    "INVALID_REPORT",
    "INVALID_PARAMETER",
    "PACKAGE_REJECTED",
    "QUERY_ERROR",
    "JOB_FAILED",
    "TIMEOUT",
    "NETWORK_ERROR",
    "RATE_LIMITED",
    "UNKNOWN_OUTCOME",
    "OUTPUT_TOO_LARGE",
)
CAPABILITIES = {
    "oracle_simulator": [
        "INSTALL_ARTIFACT",
        "VERIFY_ARTIFACT",
        "RUN_REPORT",
        "COLLECT_EVIDENCE",
    ],
    "oracle_fusion_publisher": ["CHECK_REPORT_ACCESS", "RUN_REPORT"],
}
ADAPTER_CONTRACTS = {
    "oracle_simulator": {
        "deliverables": {"PUBLISHER_SOURCE"},
        "runtime_types": {"ERP_NATIVE"},
        "modes": {"SIMULATED"},
        "operations": {"QUALIFY_CANDIDATE"},
    },
    "oracle_fusion_publisher": {
        "deliverables": {"PUBLISHER_SOURCE"},
        "runtime_types": {"ERP_NATIVE"},
        "modes": {"REMOTE"},
        "operations": {"CHECK_REPORT_ACCESS", "RUN_REPORT"},
    },
}
FUTURE_ORACLE = [
    "INSTALL_PUBLISHER_ARTIFACT",
    "VERIFY_PUBLISHER_ARTIFACT",
    "SUBMIT_ESS_JOB",
    "GET_ESS_STATUS",
    "COLLECT_ESS_LOGS",
    "CLEANUP_ARTIFACT",
]
TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "UNKNOWN_OUTCOME", "CANCELLED", "SUPERSEDED"}
TRANSITIONS = {
    "AWAITING_APPROVAL": {"QUEUED", "CANCELLED", "SUPERSEDED"},
    "QUEUED": {"DISPATCHING", "BLOCKED", "CANCELLED", "SUPERSEDED"},
    "DISPATCHING": {"REMOTE_RUNNING", "FAILED", "UNKNOWN_OUTCOME"},
    "REMOTE_RUNNING": {"COLLECTING_EVIDENCE", "FAILED", "UNKNOWN_OUTCOME"},
    "COLLECTING_EVIDENCE": {"COMPLETED", "FAILED", "UNKNOWN_OUTCOME", "SUPERSEDED"},
}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def transition(attempt, status: str) -> None:
    if status not in TRANSITIONS.get(attempt.status, set()):
        raise HTTPException(409, "invalid_execution_transition")
    attempt.status = status
    if status in TERMINAL:
        attempt.completed_at = datetime.now(UTC)


def target_policy(environment) -> None:
    allowed = (
        environment.custody == "ERPFUSION_MANAGED" and environment.environment_type == "SANDBOX"
    ) or (environment.custody == "CUSTOMER" and environment.environment_type in {"TEST", "UAT"})
    if not allowed or environment.status != "ACTIVE" or environment.archived_at is not None:
        raise HTTPException(409, "execution_target_prohibited_or_unverified")


def failure(code: str, attempt, *, phase: str, unknown: bool = False) -> dict:
    # Never put arbitrary vendor messages (which can contain customer data) here.
    categories = {
        "AUTHENTICATION_FAILED": "AUTHENTICATION",
        "PERMISSION_DENIED": "AUTHORIZATION",
        "INVALID_REPORT": "VALIDATION",
        "INVALID_PARAMETER": "VALIDATION",
        "PACKAGE_REJECTED": "INSTALLATION",
        "QUERY_ERROR": "EXECUTION",
        "JOB_FAILED": "EXECUTION",
        "TIMEOUT": "TIMEOUT",
        "NETWORK_ERROR": "CONNECTIVITY",
        "RATE_LIMITED": "RATE_LIMIT",
        "UNKNOWN_OUTCOME": "UNKNOWN_OUTCOME",
        "OUTPUT_TOO_LARGE": "OUTPUT_LIMIT",
    }
    safe_code = code if code in categories else "INFRASTRUCTURE_ERROR"
    return {
        "category": categories.get(safe_code, "INFRASTRUCTURE"),
        "vendor_code": safe_code,
        "provider": attempt.adapter,
        "phase": phase,
        "attempt_id": attempt.id,
        "retryable": not unknown and safe_code in {"RATE_LIMITED", "NETWORK_ERROR"},
        "outcome_known": not unknown,
        "safe_message": f"Operation stopped: {safe_code}.",
    }


def adapter_supports_pattern(adapter, mode, runtime_type, deliverable_type):
    contract = ADAPTER_CONTRACTS.get(adapter, {})
    return (
        mode in contract.get("modes", [])
        and runtime_type in contract.get("runtime_types", [])
        and deliverable_type in contract.get("deliverables", [])
    )


def assertions(output: bytes, plan: dict | None) -> tuple[list[dict], str]:
    """Read actual CSV. Expectations never manufacture the observed output."""
    results = []
    try:
        reader = csv.DictReader(io.StringIO(output.decode("utf-8-sig")))
        rows = list(reader)
        headers = reader.fieldnames or []
    except (UnicodeError, csv.Error):
        return [], "INCONCLUSIVE"
    for case in (plan or {}).get("required_cases", []):
        assertion = case.get("assertion", {})
        kind = assertion.get("type")
        actual: object = None
        known = True
        if kind == "CSV_ROW_COUNT":
            actual = len(rows)
        elif kind == "CSV_HEADERS":
            actual = headers
        elif kind == "CSV_REQUIRED_FIELDS":
            fields = assertion.get("fields", [])
            actual = bool(fields) and all(all(row.get(name) for name in fields) for row in rows)
        elif kind == "CSV_DECIMAL_SUM":
            try:
                actual = str(sum((Decimal(row[assertion["field"]]) for row in rows), Decimal("0")))
            except (KeyError, InvalidOperation, TypeError):
                known = False
        else:
            known = False
        status = (
            "PASSED"
            if known and actual == case["expected"]
            else "FAILED"
            if known
            else "INCONCLUSIVE"
        )
        results.append(
            {"id": case["id"], "expected": case["expected"], "actual": actual, "status": status}
        )
    verdict = (
        "INCONCLUSIVE"
        if not results or any(c["status"] == "INCONCLUSIVE" for c in results)
        else "PASSED"
        if all(c["status"] == "PASSED" for c in results)
        else "FAILED"
    )
    return results, verdict
