"""Installed protocol implementations. Catalogue entries do not install adapters."""

import asyncio
from datetime import UTC, datetime

from app.models import SimulatedArtifact
from app.services.erp_connections import ConnectionError, execute_report, probe_connection
from app.services.execution_contracts import ADAPTER_VERSION, failure
from app.services.packages import sha256

# Fixed synthetic fixture, independent of requirements and expected assertions.
SIMULATOR_OUTPUT = b"invoice_id,amount,currency\nDEMO-001,10.00,USD\n"


async def simulate(db, attempt, candidate, settings, connection=None) -> dict:
    if settings.is_production or not settings.execution_simulator_enabled:
        raise RuntimeError("execution_simulator_disabled")
    scenario = attempt.request.get("scenario") or "SUCCESS"
    now = datetime.now(UTC).isoformat()
    receipt = {
        "attempt_id": attempt.id,
        "candidate_checksum": candidate.checksum,
        "environment_id": attempt.environment_id,
        "adapter_version": ADAPTER_VERSION,
        "simulated": True,
        "recorded_at": now,
    }
    artifact = SimulatedArtifact(
        client_id=attempt.client_id,
        attempt_id=attempt.id,
        environment_id=attempt.environment_id,
        checksum=candidate.checksum,
        adapter_version=ADAPTER_VERSION,
        status="SUBMITTED",
        history=[{"status": "SUBMITTED", "at": now}],
    )
    db.add(artifact)
    await db.commit()
    artifact.status = "PROCESSING"
    artifact.history = [
        *artifact.history,
        {"status": "PROCESSING", "at": datetime.now(UTC).isoformat()},
    ]
    await db.commit()
    await asyncio.sleep(0)
    installation_failure = scenario in {
        "AUTHENTICATION_FAILED",
        "PERMISSION_DENIED",
        "INVALID_REPORT",
        "INVALID_PARAMETER",
        "PACKAGE_REJECTED",
    }
    artifact.status = "FAILED" if installation_failure else "INSTALLED"
    artifact.history = [
        *artifact.history,
        {"status": artifact.status, "at": datetime.now(UTC).isoformat()},
    ]
    await db.commit()
    # Read back the stored receipt, rather than assigning an identity assurance label.
    await db.refresh(artifact)
    verified = (
        artifact.status == "INSTALLED"
        and artifact.checksum == candidate.checksum
        and artifact.environment_id == attempt.environment_id
    )
    receipt.update(
        artifact_id=artifact.id,
        installation_history=artifact.history,
        identity_verified=verified,
        read_back_checksum=artifact.checksum,
        remote_exact_bytes_verified=False,
    )
    if scenario != "SUCCESS":
        unknown = scenario in {"UNKNOWN_OUTCOME", "TIMEOUT"}
        return {
            "output": b"",
            "receipt": receipt,
            "failure": failure(
                scenario,
                attempt,
                phase="install" if installation_failure else "execute",
                unknown=unknown,
            ),
            "external_execution_id": f"sim-{attempt.id}",
            "assurance": ["SIMULATED_INSTALLATION"] if verified else [],
        }
    receipt["execution_history"] = ["QUEUED", "RUNNING", "COMPLETED"]
    return {
        "output": SIMULATOR_OUTPUT,
        "receipt": receipt,
        "failure": {},
        "external_execution_id": f"sim-{attempt.id}",
        "assurance": ["SIMULATED_INSTALLATION", "SIMULATED_EXECUTION"],
    }


async def oracle(db, attempt, candidate, settings, connection=None) -> dict:
    """Only a configured existing report. No install or candidate identity claim."""
    receipt = {
        "attempt_id": attempt.id,
        "candidate_checksum": attempt.candidate_checksum,
        "environment_id": attempt.environment_id,
        "simulated": False,
        "adapter_version": ADAPTER_VERSION,
        "remote_exact_bytes_verified": False,
        "installation": "NOT_IMPLEMENTED",
        "identity_verified": False,
    }
    try:
        if attempt.operation == "CHECK_REPORT_ACCESS":
            checks, code = await probe_connection(connection, settings)
            passed = (
                checks.get("authentication") == "VERIFIED"
                and checks.get("permissions") == "VERIFIED"
            )
            return {
                "output": b"",
                "receipt": {**receipt, "checks": checks},
                "failure": {} if passed else failure("PERMISSION_DENIED", attempt, phase="check"),
                "assurance": [],
                "external_execution_id": None,
            }
        output, metadata = await execute_report(
            connection,
            attempt.request.get("parameters", {}),
            settings,
            expected_configuration_version=attempt.binding["connection_version"],
            expected_secret_version=attempt.binding["secret_version"],
        )
        return {
            "output": output,
            "receipt": {**receipt, **metadata, "output_sha256": sha256(output)},
            "failure": {},
            "assurance": ["REMOTE_EXECUTION_OBSERVED"],
            "external_execution_id": None,
        }
    except ConnectionError as exc:
        # Existing transport emits stable codes; unrecognized text is never echoed.
        code = {
            "authentication_rejected": "AUTHENTICATION_FAILED",
            "permission_denied": "PERMISSION_DENIED",
            "invalid_report_parameters": "INVALID_PARAMETER",
            "response_too_large": "OUTPUT_TOO_LARGE",
        }.get(str(exc), "INFRASTRUCTURE_ERROR")
        unknown = attempt.operation == "RUN_REPORT" and code == "INFRASTRUCTURE_ERROR"
        return {
            "output": b"",
            "receipt": receipt,
            "failure": failure(code, attempt, phase="execute", unknown=unknown),
            "assurance": [],
            "external_execution_id": None,
        }


# Both implementations share only the execution envelope; vendor operations stay specific.
INSTALLED_EXECUTORS = {"oracle_simulator": simulate, "oracle_fusion_publisher": oracle}
