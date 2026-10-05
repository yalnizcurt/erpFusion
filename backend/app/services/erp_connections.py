"""Bounded, pinned HTTPS and Secrets Manager access for approved Fusion reports.

No fallback credentials, redirects, private-network targets, or catalog writes.
Vendor bodies and SDK exceptions must never escape as diagnostics or audit content.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
import uuid
from contextlib import closing
from importlib import import_module
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from pydantic import ValidationError

from app.config import Settings
from app.models.connection import ERPConnection
from app.schemas.connections import ConnectionConfigure, ConnectionCredentials

SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
PUB = "http://xmlns.oracle.com/oxp/service/PublicReportService"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
SERVICE_PATH = "/xmlpserver/services/ExternalReportWSSService"


class ConnectionError(RuntimeError):
    """Only safe, stable codes may cross the service boundary."""


def validate_destination(
    connection: ConnectionConfigure | ERPConnection, settings: Settings
) -> str:
    # Validate persisted metadata too, rather than trusting historic writes.
    try:
        config = ConnectionConfigure.model_validate(
            {field: getattr(connection, field) for field in ConnectionConfigure.model_fields}
        )
    except ValidationError:
        raise ConnectionError("invalid_connection_configuration") from None
    host = urlsplit(config.source_url).hostname
    allowed = getattr(settings, "erp_allowed_hosts", [])
    if not host or host not in allowed or host not in config.approved_hosts:
        raise ConnectionError("destination_not_approved")
    return host


def _public_addresses(host: str) -> list[str]:
    try:
        addresses = sorted(
            {str(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        )
    except OSError:
        raise ConnectionError("dns_failed") from None
    if not addresses or any(
        not ipaddress.ip_address(ip).is_global
        or ipaddress.ip_address(ip).is_multicast
        or ipaddress.ip_address(ip).is_reserved
        for ip in addresses
    ):
        raise ConnectionError("private_destination_blocked")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float):
        self.tls_context = ssl.create_default_context()
        super().__init__(host, port=443, timeout=timeout, context=self.tls_context)
        self.address = address
        self._raw_socket: socket.socket | None = None
        self._tls_socket: ssl.SSLSocket | None = None
        self.deadline = time.monotonic() + timeout

    def connect(self) -> None:
        # Connect only the approved resolved IP; preserve hostname TLS/SNI checks.
        self._raw_socket = socket.create_connection((self.address, 443), self.timeout)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        self._raw_socket.settimeout(remaining)
        self._tls_socket = self.tls_context.wrap_socket(self._raw_socket, server_hostname=self.host)
        self.sock = self._tls_socket

    def abort(self) -> None:
        for stream in (self._tls_socket, self._raw_socket):
            if stream:
                try:
                    stream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


def _request(host: str, address: str, body: bytes | None, settings: Settings) -> tuple[int, bytes]:
    timeout = float(getattr(settings, "erp_connection_timeout_seconds", 10))
    maximum = int(getattr(settings, "erp_max_response_bytes", 8 * 1024 * 1024))
    connection = _PinnedHTTPSConnection(host, address, timeout)
    deadline = time.monotonic() + timeout
    timer = threading.Timer(timeout, connection.abort)
    timer.daemon = True
    timer.start()
    try:
        connection.request(
            "POST" if body else "GET",
            SERVICE_PATH if body else SERVICE_PATH + "?wsdl",
            body=body,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '""',
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ConnectionError("redirect_blocked")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ConnectionError("compressed_response_blocked")
        length = response.getheader("Content-Length")
        if length and (not length.isdecimal() or int(length) > maximum):
            raise ConnectionError("response_too_large")
        chunks, count = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConnectionError("connection_timeout")
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read(min(65536, maximum + 1 - count))
            if not chunk:
                break
            chunks.append(chunk)
            count += len(chunk)
            if count > maximum:
                raise ConnectionError("response_too_large")
        return response.status, b"".join(chunks)
    except ssl.SSLCertVerificationError:
        raise ConnectionError("tls_certificate_invalid") from None
    except TimeoutError:
        raise ConnectionError("connection_timeout") from None
    except ConnectionError:
        raise
    except (OSError, http.client.HTTPException, ValueError):
        code = "connection_timeout" if time.monotonic() >= deadline else "network_failed"
        raise ConnectionError(code) from None
    finally:
        timer.cancel()
        connection.close()


async def _send(
    connection: ERPConnection, settings: Settings, body: bytes | None
) -> tuple[int, bytes]:
    host = validate_destination(connection, settings)
    timeout = float(getattr(settings, "erp_connection_timeout_seconds", 10))
    try:
        addresses = await asyncio.wait_for(asyncio.to_thread(_public_addresses, host), timeout)
        return await asyncio.wait_for(
            asyncio.to_thread(_request, host, addresses[0], body, settings), timeout + 1
        )
    except TimeoutError:
        raise ConnectionError("connection_timeout") from None


def _secret_client(settings: Settings) -> Any:
    if not getattr(settings, "erp_secret_prefix", "") or not settings.aws_region:
        raise ConnectionError("secret_store_not_configured")
    try:
        boto3 = import_module("boto3")
        config = import_module("botocore.config").Config
        return boto3.client(
            "secretsmanager",
            region_name=settings.aws_region,
            config=config(
                connect_timeout=2,
                read_timeout=3,
                retries={"total_max_attempts": 1},
                ignore_configured_endpoint_urls=True,
            ),
        )
    except Exception:
        raise ConnectionError("secret_store_unavailable") from None


def _secret_tags(connection: ERPConnection) -> dict[str, str]:
    return {
        "client_id": connection.client_id,
        "installation_id": connection.installation_id,
        "environment_id": connection.environment_id,
        "connection_id": connection.id,
        "operation": "fusion_report_read",
    }


def _write_credentials(
    connection: ERPConnection, credentials: ConnectionCredentials, settings: Settings
) -> tuple[str, str]:
    tags = _secret_tags(connection)
    name = (
        f"{getattr(settings, 'erp_secret_prefix', '').rstrip('/')}/{connection.client_id}/"
        f"{connection.installation_id}/{connection.environment_id}/{connection.id}/{uuid.uuid4()}"
    )
    try:
        with closing(_secret_client(settings)) as client:
            arguments = {
                "Name": name,
                "SecretString": json.dumps(
                    {
                        "username": credentials.username.get_secret_value(),
                        "password": credentials.password.get_secret_value(),
                    }
                ),
                "Tags": [{"Key": key, "Value": value} for key, value in tags.items()],
            }
            if getattr(settings, "erp_secret_kms_key_id", ""):
                arguments["KmsKeyId"] = settings.erp_secret_kms_key_id
            response = client.create_secret(**arguments)
            return response["ARN"], response["VersionId"]
    except ConnectionError:
        raise
    except Exception:
        raise ConnectionError("secret_store_write_failed") from None


async def write_credentials(
    connection: ERPConnection, credentials: ConnectionCredentials, settings: Settings
) -> tuple[str, str]:
    validate_destination(connection, settings)
    return await asyncio.to_thread(_write_credentials, connection, credentials, settings)


def _read_credentials(connection: ERPConnection, settings: Settings) -> ConnectionCredentials:
    if not connection.secret_ref or not connection.secret_version:
        raise ConnectionError("credentials_not_configured")
    prefix = getattr(settings, "erp_secret_prefix", "").rstrip("/")
    expected_name = (
        f"{prefix}/{connection.client_id}/{connection.installation_id}/"
        f"{connection.environment_id}/{connection.id}/"
    )
    # Fail before fetching an arbitrary secret reference from modified database rows.
    reference = connection.secret_ref.split(":", 6)
    if (
        len(reference) != 7
        or reference[0] != "arn"
        or reference[5] != "secret"
        or reference[2] != "secretsmanager"
        or reference[3] != settings.aws_region
        or not reference[6].startswith(expected_name)
    ):
        raise ConnectionError("secret_scope_mismatch")
    try:
        with closing(_secret_client(settings)) as client:
            metadata = client.describe_secret(SecretId=connection.secret_ref)
            tags = {item["Key"]: item["Value"] for item in metadata.get("Tags", [])}
            if any(tags.get(key) != value for key, value in _secret_tags(connection).items()):
                raise ConnectionError("secret_scope_mismatch")
            # A changed current version immediately invalidates old Ping/job evidence.
            if "AWSCURRENT" not in metadata.get("VersionIdsToStages", {}).get(
                connection.secret_version, []
            ):
                raise ConnectionError("secret_version_changed")
            response = client.get_secret_value(
                SecretId=connection.secret_ref, VersionId=connection.secret_version
            )
            if response.get("VersionId") != connection.secret_version:
                raise ConnectionError("secret_version_changed")
            raw = response.get("SecretString", "")
            if len(raw) > 8192:
                raise ConnectionError("secret_invalid")
            return ConnectionCredentials.model_validate(json.loads(raw))
    except ConnectionError:
        raise
    except Exception:
        raise ConnectionError("secret_store_read_failed") from None


async def read_credentials(connection: ERPConnection, settings: Settings) -> ConnectionCredentials:
    validate_destination(connection, settings)
    return await asyncio.to_thread(_read_credentials, connection, settings)


def _envelope(credentials: ConnectionCredentials, operation: str) -> tuple[ET.Element, ET.Element]:
    envelope = ET.Element(f"{{{SOAP}}}Envelope")
    header = ET.SubElement(envelope, f"{{{SOAP}}}Header")
    security = ET.SubElement(header, f"{{{WSSE}}}Security", {f"{{{SOAP}}}mustUnderstand": "1"})
    token = ET.SubElement(security, f"{{{WSSE}}}UsernameToken")
    ET.SubElement(token, f"{{{WSSE}}}Username").text = credentials.username.get_secret_value()
    ET.SubElement(
        token,
        f"{{{WSSE}}}Password",
        {
            "Type": "http://docs.oasis-open.org/wss/2004/01/"
            "oasis-200401-wss-username-token-profile-1.0#PasswordText"
        },
    ).text = credentials.password.get_secret_value()
    body = ET.SubElement(envelope, f"{{{SOAP}}}Body")
    return envelope, ET.SubElement(body, f"{{{PUB}}}{operation}")


def _parse_response(status: int, data: bytes) -> ET.Element:
    if status in (401, 403):
        raise ConnectionError("authentication_rejected" if status == 401 else "permission_denied")
    # Reject non UTF-8 payloads before parsing so UTF-16 cannot conceal declarations.
    try:
        xml = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConnectionError("invalid_soap_response") from None
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ConnectionError("unsafe_xml_blocked")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise ConnectionError("invalid_soap_response") from None
    if root.tag != f"{{{SOAP}}}Envelope" or root.find(f"{{{SOAP}}}Body") is None:
        raise ConnectionError("invalid_soap_response")
    if root.find(f".//{{{SOAP}}}Fault") is not None:
        # Recognize standard security faults; never return fault content/vendor messages.
        fault = " ".join(root.itertext()).lower()
        if any(code in fault for code in ("failedauthentication", "invalidsecuritytoken")):
            raise ConnectionError("authentication_rejected")
        if "access denied" in fault or "permission" in fault:
            raise ConnectionError("permission_denied")
        raise ConnectionError("soap_fault")
    if status != 200:
        raise ConnectionError("vendor_http_error")
    return root


async def probe_connection(connection: ERPConnection, settings: Settings) -> tuple[dict, str]:
    checks = {
        "network": "NOT_VERIFIED",
        "authentication": "NOT_VERIFIED",
        "tenant": "NOT_VERIFIED",
        "permissions": "NOT_VERIFIED",
        "report_execution": "NOT_VERIFIED",
        "import_capability": "UNSUPPORTED",
    }
    try:
        if "PING" not in connection.permitted_operations:
            raise ConnectionError("operation_not_permitted")
        credentials = await read_credentials(connection, settings)
        status, _ = await _send(connection, settings, None)
        checks["network"] = "VERIFIED"
        if status >= 500:
            raise ConnectionError("vendor_http_error")
        envelope, operation = _envelope(credentials, "hasReportAccess")
        ET.SubElement(operation, f"{{{PUB}}}reportAbsolutePath").text = connection.report_path
        status, data = await _send(connection, settings, ET.tostring(envelope, encoding="utf-8"))
        root = _parse_response(status, data)
        result = root.find(f".//{{{PUB}}}hasReportAccessResponse/{{{PUB}}}hasReportAccessReturn")
        if result is None or result.text not in ("true", "false", "1", "0"):
            raise ConnectionError("invalid_soap_response")
        checks["authentication"] = "VERIFIED"
        checks["permissions"] = "VERIFIED" if result.text in ("true", "1") else "FAILED"
        # Access is not proof of execution or identity; approved jobs provide those observations.
        return checks, "tenant_and_execution_not_verified" if checks[
            "permissions"
        ] == "VERIFIED" else "permission_denied"
    except ConnectionError as exc:
        code = str(exc)
        if code == "authentication_rejected":
            checks["authentication"] = "FAILED"
        elif code == "permission_denied":
            checks["permissions"] = "FAILED"
        elif checks["network"] != "VERIFIED":
            checks["network"] = "BLOCKED"
        return checks, code


async def execute_report(
    connection: ERPConnection,
    parameters: dict[str, list[str]],
    settings: Settings,
    *,
    expected_configuration_version: int,
    expected_secret_version: str,
    report_path: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Execute only the configured report; the caller must approve the exact job first.

    Caller persists returned output using private artifact storage and audits these
    metadata identifiers against the approved candidate. No raw response is logged.
    """
    if (
        connection.configuration_version != expected_configuration_version
        or connection.secret_version != expected_secret_version
    ):
        raise ConnectionError("connection_version_changed")
    if "RUN_REPORT" not in connection.permitted_operations:
        raise ConnectionError("operation_not_permitted")
    if report_path is not None and report_path != connection.report_path:
        raise ConnectionError("report_not_approved")
    if (
        not isinstance(parameters, dict)
        or len(parameters) > 30
        or any(
            not isinstance(name, str)
            or not 1 <= len(name) <= 128
            or any(ord(char) < 32 for char in name)
            or not isinstance(values, list)
            or len(values) > 100
            or any(
                not isinstance(value, str)
                or len(value) > 2048
                or any(ord(char) < 32 for char in value)
                for value in values
            )
            for name, values in parameters.items()
        )
    ):
        raise ConnectionError("invalid_report_parameters")
    if len(json.dumps(parameters).encode("utf-8")) > 65536:
        raise ConnectionError("invalid_report_parameters")
    credentials = await read_credentials(connection, settings)
    envelope, operation = _envelope(credentials, "runReport")
    request = ET.SubElement(operation, f"{{{PUB}}}reportRequest")
    ET.SubElement(request, f"{{{PUB}}}attributeFormat").text = "csv"
    ET.SubElement(request, f"{{{PUB}}}reportAbsolutePath").text = connection.report_path
    ET.SubElement(request, f"{{{PUB}}}sizeOfDataChunkDownload").text = "-1"
    parameter_values = ET.SubElement(request, f"{{{PUB}}}parameterNameValues")
    parameter_items = ET.SubElement(parameter_values, f"{{{PUB}}}listOfParamNameValues")
    for name, values in sorted(parameters.items()):
        item = ET.SubElement(parameter_items, f"{{{PUB}}}item")
        ET.SubElement(item, f"{{{PUB}}}name").text = name
        container = ET.SubElement(item, f"{{{PUB}}}values")
        for value in values:
            ET.SubElement(container, f"{{{PUB}}}item").text = value
    status, data = await _send(connection, settings, ET.tostring(envelope, encoding="utf-8"))
    root = _parse_response(status, data)
    result = root.find(f".//{{{PUB}}}runReportResponse/{{{PUB}}}runReportReturn")
    encoded = result.find(f"{{{PUB}}}reportBytes") if result is not None else None
    if result is None or encoded is None or not encoded.text:
        raise ConnectionError("report_output_missing")
    try:
        output = base64.b64decode("".join(encoded.text.split()), validate=True)
    except (ValueError, binascii.Error):
        raise ConnectionError("report_output_invalid") from None
    if len(output) > int(getattr(settings, "erp_max_response_bytes", 8 * 1024 * 1024)):
        raise ConnectionError("response_too_large")
    content_type = result.find(f"{{{PUB}}}reportContentType")
    if content_type is None or content_type.text not in ("text/csv", "application/csv"):
        raise ConnectionError("report_content_type_unexpected")
    return output, {
        "connection_id": connection.id,
        "client_id": connection.client_id,
        "environment_id": connection.environment_id,
        "configuration_version": connection.configuration_version,
        "secret_version": connection.secret_version,
        "report_path": connection.report_path,
        "parameters_sha256": hashlib.sha256(
            json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "output_bytes": len(output),
        "content_type": "text/csv",
        "adapter": "oracle_fusion_publisher",
    }
