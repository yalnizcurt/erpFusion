"""Connection safety checks use local fixtures, never ERP endpoints or real secrets."""

import base64
import socket
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import connections
from app.config import get_settings
from app.database import get_db
from app.models import AdminAuditEvent, Base, Client, ERPEnvironment, ERPInstallation, ERPProfile
from app.models.connection import ConnectionVerification, ERPConnection
from app.schemas.connections import ConnectionConfigure, ConnectionCredentials
from app.security.identity import Identity, get_current_identity
from app.services import erp_connections as service

CONFIG = {
    "source_url": "https://approved.oraclecloud.com",
    "expected_tenant": "client-sandbox",
    "approved_hosts": ["approved.oraclecloud.com"],
    "report_path": "/Custom/Demo/Invoices.xdo",
    "permitted_operations": ["PING", "RUN_REPORT"],
}


def config_settings():
    return SimpleNamespace(
        aws_region="us-east-1",
        erp_allowed_hosts=["approved.oraclecloud.com"],
        erp_secret_prefix="erp",
        erp_secret_kms_key_id="",
        erp_connection_timeout_seconds=1,
        erp_max_response_bytes=8192,
        erp_probe_ttl_seconds=300,
    )


def connection():
    return ERPConnection(
        id="connection",
        client_id="client",
        installation_id="installation",
        environment_id="environment",
        configuration_version=2,
        secret_ref="arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "erp/client/installation/environment/connection/credentials-ABCDEF",
        secret_version="secret-version",
        adapter="oracle_fusion_publisher",
        vendor_configuration={},
        **CONFIG,
    )


def soap(operation, content):
    return (
        f'<s:Envelope xmlns:s="{service.SOAP}" xmlns:p="{service.PUB}"><s:Body>'
        f"<p:{operation}Response><p:{operation}Return>{content}</p:{operation}Return>"
        f"</p:{operation}Response></s:Body></s:Envelope>"
    ).encode()


@pytest.mark.parametrize(
    "url",
    [
        "http://approved.oraclecloud.com",
        "https://user:password@approved.oraclecloud.com",
        "https://approved.oraclecloud.com:8443",
        "https://approved.oraclecloud.com/internal",
        "https://approved.oraclecloud.com?target=internal",
        "https://approved.oraclecloud.com\n",
    ],
)
def test_only_https_origins_accepted(url):
    with pytest.raises(ValidationError):
        ConnectionConfigure(**{**CONFIG, "source_url": url})


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "fd00::1", "224.0.0.1", "::ffff:127.0.0.1"],
)
def test_dns_private_metadata_multicast_targets_blocked(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(service.ConnectionError, match="private_destination_blocked"):
        service._public_addresses("approved.oraclecloud.com")


def test_allowlist_required_before_dns_or_secret_lookup():
    settings = config_settings()
    settings.erp_allowed_hosts = []
    with pytest.raises(service.ConnectionError, match="destination_not_approved"):
        service.validate_destination(connection(), settings)


@pytest.mark.asyncio
async def test_pins_address_and_never_uses_proxy_or_second_dns_lookup(monkeypatch):
    seen = []
    monkeypatch.setattr(service, "_public_addresses", lambda host: ["8.8.8.8"])
    monkeypatch.setattr(
        service,
        "_request",
        lambda host, address, body, settings: seen.append((host, address)) or (200, b"safe"),
    )
    assert await service._send(connection(), config_settings(), None) == (200, b"safe")
    assert seen == [("approved.oraclecloud.com", "8.8.8.8")]


def test_redirect_never_forwarded(monkeypatch):
    class Transport:
        sock = None

        def __init__(self, *args):
            self.calls = []

        def abort(self):
            pass

        def request(self, *args, **kwargs):
            self.calls.append(args)

        def getresponse(self):
            return SimpleNamespace(status=302)

        def close(self):
            pass

    monkeypatch.setattr(service, "_PinnedHTTPSConnection", Transport)
    with pytest.raises(service.ConnectionError, match="redirect_blocked"):
        service._request("approved.oraclecloud.com", "8.8.8.8", b"sensitive", config_settings())


@pytest.mark.parametrize(
    "status,body,code",
    [
        (401, b"private password", "authentication_rejected"),
        (403, b"private password", "permission_denied"),
        (200, b"<html>login</html>", "invalid_soap_response"),
        (
            200,
            b'<!DOCTYPE x [<!ENTITY private SYSTEM "file:///etc/passwd">]><x/>',
            "unsafe_xml_blocked",
        ),
        (200, "<!DOCTYPE x><x/>".encode("utf-16"), "invalid_soap_response"),
        (
            500,
            f'<s:Envelope xmlns:s="{service.SOAP}"><s:Body><s:Fault><faultcode>'
            "wsse:FailedAuthentication</faultcode><faultstring>private</faultstring>"
            "</s:Fault></s:Body></s:Envelope>".encode(),
            "authentication_rejected",
        ),
    ],
)
def test_safe_soap_failure_codes(status, body, code):
    with pytest.raises(service.ConnectionError) as error:
        service._parse_response(status, body)
    assert str(error.value) == code
    assert "private" not in str(error.value)


def test_secret_scope_and_rotated_versions_fail_closed(monkeypatch):
    target = connection()
    target.secret_ref = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:another-client/private"
    )
    with pytest.raises(service.ConnectionError, match="secret_scope_mismatch"):
        service._read_credentials(target, config_settings())

    class Store:
        def describe_secret(self, **kw):
            return {
                "Tags": [
                    {"Key": k, "Value": v} for k, v in service._secret_tags(connection()).items()
                ],
                "VersionIdsToStages": {"new-version": ["AWSCURRENT"]},
            }

        def get_secret_value(self, **kw):
            pytest.fail("Do not fetch stale secret")

        def close(self):
            pass

    monkeypatch.setattr(service, "_secret_client", lambda settings: Store())
    with pytest.raises(service.ConnectionError, match="secret_version_changed"):
        service._read_credentials(connection(), config_settings())


@pytest.mark.asyncio
async def test_missing_secret_and_auth_failure_are_layered(monkeypatch):
    target = connection()
    target.secret_ref = None
    checks, code = await service.probe_connection(target, config_settings())
    assert code == "credentials_not_configured"
    assert checks["authentication"] == "NOT_VERIFIED"
    assert checks["network"] == "BLOCKED"

    async def credentials(*args):
        return ConnectionCredentials(username="fixture-account", password="fixture-secret")

    async def send(*args):
        return (401, b"secret") if args[2] else (200, b"wsdl")

    monkeypatch.setattr(service, "read_credentials", credentials)
    monkeypatch.setattr(service, "_send", send)
    checks, code = await service.probe_connection(connection(), config_settings())
    assert checks["network"] == "VERIFIED" and checks["authentication"] == "FAILED"
    assert checks["tenant"] == "NOT_VERIFIED"
    assert checks["import_capability"] == "UNSUPPORTED"
    assert code == "authentication_rejected"


@pytest.mark.asyncio
async def test_report_execution_is_exact_and_returns_hash_evidence(monkeypatch):
    async def credentials(*args):
        return ConnectionCredentials(username="fixture-account", password="fixture-secret")

    payload = b"INVOICE_ID,AMOUNT\n1,10.00\n"

    async def send(target, settings, body):
        xml = service.ET.fromstring(body)
        assert xml.find(f".//{{{service.WSSE}}}Username").text == "fixture-account"
        assert xml.find(f".//{{{service.PUB}}}reportAbsolutePath").text == CONFIG["report_path"]
        assert xml.find(f".//{{{service.PUB}}}userID") is None
        assert (
            xml.find(
                f".//{{{service.PUB}}}parameterNameValues/{{{service.PUB}}}listOfParamNameValues/"
                f"{{{service.PUB}}}item/{{{service.PUB}}}name"
            ).text
            == "P_BU"
        )
        return 200, soap(
            "runReport",
            "<p:reportContentType>text/csv</p:reportContentType>"
            f"<p:reportBytes>{base64.b64encode(payload).decode()}</p:reportBytes>",
        )

    monkeypatch.setattr(service, "read_credentials", credentials)
    monkeypatch.setattr(service, "_send", send)
    target, settings = connection(), config_settings()
    kwargs = {"expected_configuration_version": 2, "expected_secret_version": "secret-version"}
    output, evidence = await service.execute_report(target, {"P_BU": ["Demo"]}, settings, **kwargs)
    assert (
        output == payload
        and evidence["output_sha256"] == service.hashlib.sha256(payload).hexdigest()
    )
    assert "fixture-secret" not in str(evidence)
    for error_code, changes in [
        ("connection_version_changed", {"expected_configuration_version": 1}),
        ("connection_version_changed", {"expected_secret_version": "old-version"}),
        ("report_not_approved", {"report_path": "/Custom/Other.xdo"}),
    ]:
        with pytest.raises(service.ConnectionError, match=error_code):
            await service.execute_report(target, {}, settings, **{**kwargs, **changes})
    target.permitted_operations = ["PING"]
    with pytest.raises(service.ConnectionError, match="operation_not_permitted"):
        await service.execute_report(target, {}, settings, **kwargs)


@pytest.mark.asyncio
async def test_connection_api_permissions_redaction_audit_and_invalidation(monkeypatch):
    def unavailable(_settings):
        raise service.ConnectionError("secret_store_unavailable")

    monkeypatch.setattr(service, "_secret_client", unavailable)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    async with factory() as db:
        owner = Client(id="client", client_key="fixture", display_name="Fixture")
        profile = ERPProfile(id="profile", key="fixture", name="Fixture", vendor="Fixture")
        db.add_all([owner, profile])
        await db.flush()
        installation = ERPInstallation(
            id="installation",
            client_id="client",
            erp_profile_id="profile",
            installation_key="fixture",
            display_name="Fixture",
        )
        db.add(installation)
        await db.flush()
        db.add(
            ERPEnvironment(
                id="environment",
                client_id="client",
                installation_id="installation",
                environment_key="sandbox",
                display_name="Sandbox",
            )
        )
        await db.commit()

    async def sessions():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    actor = Identity(user_id="admin", provider="direct-test", roles=frozenset({"platform_admin"}))
    app = FastAPI()
    app.include_router(connections.router)
    app.dependency_overrides[get_db] = sessions
    app.dependency_overrides[get_settings] = config_settings
    app.dependency_overrides[get_current_identity] = lambda: actor
    path = "/api/clients/client/installations/installation/environments/environment/connection"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            assert (await http.put(path, json=CONFIG)).status_code == 200
            bad = await http.put(
                path + "/credentials",
                json={"username": "private-account", "password": "", "extra": "private-secret"},
            )
            assert bad.status_code == 422 and "private" not in bad.text
            failed = await http.put(
                path + "/credentials", json={"username": "fixture", "password": "fixture"}
            )
            # No fake local credential store: missing runtime AWS dependency/IAM fails closed.
            assert failed.status_code == 503
            assert "fixture" not in failed.text
            actor = Identity(user_id="outsider", provider="direct-test")
            assert (await http.get(path)).status_code == 404
            assert (await http.post(path + "/ping")).status_code == 403
            actor = Identity(
                user_id="admin", provider="direct-test", roles=frozenset({"platform_admin"})
            )
            ping = await http.post(path + "/ping")
            assert (
                ping.status_code == 200
                and ping.json()["diagnostic_code"] == "credentials_not_configured"
            )
            version = ping.json()["configuration_version"]
            changed = await http.put(path, json=CONFIG)
            assert changed.json()["configuration_version"] == version + 1
            assert changed.json()["last_verification"]["current"] is False
            assert "secret_ref" not in changed.text and "password" not in changed.text
            for _ in range(4):
                assert (await http.post(path + "/ping")).status_code == 200
            assert (await http.post(path + "/ping")).status_code == 429
        async with factory() as db:
            events = (await db.execute(select(AdminAuditEvent))).scalars().all()
            assert {e.action for e in events} >= {"CONNECTION_CONFIGURED", "CONNECTION_CHECKED"}
            assert all(e.client_id == "client" for e in events)
            assert len((await db.execute(select(ConnectionVerification))).scalars().all()) == 5
    finally:
        await engine.dispose()
