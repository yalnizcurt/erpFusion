"""Authentication, issuer isolation, role separation, and read-only identity regressions."""

import json
import time
from collections.abc import AsyncIterator

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.admin_auth import require_erp_admin, require_erp_publisher
from app.api.identity import current_identity
from app.config import Settings
from app.main import create_app
from app.models import Base, Client, ClientMembership, IdentitySubject, PlatformRoleAssignment
from app.schemas.identity import ClientMembershipCreate, ERPEnvironmentCreate, ERPInstallationCreate
from app.security.access import ensure_client_access, identity_client_ids
from app.security.identity import Identity, get_current_identity
from app.security.oidc import (
    IdentityProviderUnavailableError,
    InvalidIdentityTokenError,
    OIDCVerifier,
)


def configured(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        auth_mode="oidc",
        **(
            {
                "oidc_issuer": "https://identity.example.test",
                "oidc_audience": "erpfusion",
                "oidc_jwks_url": "https://identity.example.test/keys",
            }
            | overrides
        ),
    )


@pytest.fixture(scope="module")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    return private, public | {"kid": "current", "alg": "RS256", "use": "sig"}


def access_token(keypair, **overrides):
    now = int(time.time())
    claims = {
        "sub": "verified-user",
        "iss": "https://identity.example.test",
        "aud": "erpfusion",
        "iat": now,
        "exp": now + 300,
    } | overrides
    return jwt.encode(claims, keypair[0], algorithm="RS256", headers={"kid": "current"})


def verifier_for(keypair, settings=None):
    return OIDCVerifier(
        settings or configured(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"keys": [keypair[1]]}),
        ),
    )


@pytest.mark.asyncio
async def test_signed_token_uses_pinned_issuer_audience_and_cached_key(keypair):
    requests = []
    verifier = OIDCVerifier(
        configured(),
        transport=httpx.MockTransport(
            lambda request: (
                requests.append(request) or httpx.Response(200, json={"keys": [keypair[1]]})
            )
        ),
    )
    token = access_token(keypair, roles=["platform_admin"], client_ids=["foreign"])
    assert (await verifier.verify(token))["sub"] == "verified-user"
    await verifier.verify(token)
    assert len(requests) == 1
    assert str(requests[0].url) == "https://identity.example.test/keys"


@pytest.mark.asyncio
async def test_cognito_access_token_requires_configured_client_id_and_token_use(keypair):
    settings = configured(oidc_audience_claim="client_id", oidc_token_use="access")
    verifier = verifier_for(keypair, settings)
    token = access_token(keypair, aud=None, client_id="erpfusion", token_use="access")
    assert (await verifier.verify(token))["client_id"] == "erpfusion"
    for overrides in (
        {"client_id": "foreign-client"},
        {"client_id": ["erpfusion"]},
        {"token_use": "id"},
        {"token_use": None},
    ):
        rejected = access_token(
            keypair, **({"client_id": "erpfusion", "token_use": "access"} | overrides)
        )
        with pytest.raises(InvalidIdentityTokenError):
            await verifier.verify(rejected)
    # The default generic OIDC verifier continues to require a real aud claim.
    with pytest.raises(InvalidIdentityTokenError):
        await verifier_for(keypair).verify(token)


@pytest.mark.asyncio
async def test_cognito_access_token_may_omit_aud_but_never_client_id(keypair):
    settings = configured(oidc_audience_claim="client_id", oidc_token_use="access")
    claims = jwt.decode(access_token(keypair), options={"verify_signature": False})
    del claims["aud"]
    claims.update(client_id="erpfusion", token_use="access")
    token = jwt.encode(claims, keypair[0], algorithm="RS256", headers={"kid": "current"})
    assert (await verifier_for(keypair, settings).verify(token))["sub"] == "verified-user"
    del claims["client_id"]
    token = jwt.encode(claims, keypair[0], algorithm="RS256", headers={"kid": "current"})
    with pytest.raises(InvalidIdentityTokenError):
        await verifier_for(keypair, settings).verify(token)


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.example.test"},
        {"aud": "other-app"},
        {"exp": 100},
        {"iat": int(time.time()) + 300},
        {"sub": ""},
        {"sub": 123},
        {"iat": "123"},
        {"exp": None},
    ],
)
@pytest.mark.asyncio
async def test_invalid_registered_claims_are_rejected(keypair, overrides):
    with pytest.raises(InvalidIdentityTokenError):
        await verifier_for(keypair).verify(access_token(keypair, **overrides))


@pytest.mark.asyncio
async def test_wrong_signature_and_weak_algorithm_rejected(keypair):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(InvalidIdentityTokenError):
        await verifier_for(keypair).verify(access_token((other, keypair[1])))
    token = jwt.encode(
        {"sub": "attacker"}, "fixture-key" * 4, algorithm="HS256", headers={"kid": "current"}
    )
    with pytest.raises(InvalidIdentityTokenError):
        await verifier_for(keypair).verify(token)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://untrusted.example.test/keys"}),
        httpx.Response(200, content=b"x" * 262_145),
        httpx.Response(200, json={"keys": []}),
        httpx.Response(503, text="private provider response"),
    ],
)
@pytest.mark.asyncio
async def test_jwks_unavailable_or_unsafe_response_fails_closed(keypair, response):
    verifier = OIDCVerifier(configured(), transport=httpx.MockTransport(lambda request: response))
    with pytest.raises(IdentityProviderUnavailableError) as error:
        await verifier.verify(access_token(keypair))
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_unknown_key_refresh_is_bounded_and_rotation_is_supported(keypair):
    requests = []
    verifier = OIDCVerifier(
        configured(),
        transport=httpx.MockTransport(
            lambda request: (
                requests.append(request) or httpx.Response(200, json={"keys": [keypair[1]]})
            )
        ),
    )
    await verifier.verify(access_token(keypair))
    unknown = jwt.encode({"sub": "a"}, keypair[0], algorithm="RS256", headers={"kid": "unknown"})
    for _ in range(3):
        with pytest.raises(InvalidIdentityTokenError):
            await verifier.verify(unknown)
    assert len(requests) == 1
    verifier._last_refresh -= 31
    rotated_public = keypair[1] | {"kid": "rotated"}
    verifier.transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"keys": [rotated_public]})
    )
    rotated = jwt.encode(
        jwt.decode(access_token(keypair), options={"verify_signature": False}),
        keypair[0],
        algorithm="RS256",
        headers={"kid": "rotated"},
    )
    assert (await verifier.verify(rotated))["sub"] == "verified-user"


@pytest.mark.parametrize("active", [False, None, "true"])
@pytest.mark.asyncio
async def test_optional_introspection_rejects_revoked_session(keypair, active):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json=({"keys": [keypair[1]]} if request.method == "GET" else {"active": active})
        )

    settings = configured(
        oidc_introspection_url="https://identity.example.test/introspect",
        oidc_introspection_client_id="portal",
        oidc_introspection_client_secret="fixture-secret",
    )
    verifier = OIDCVerifier(settings, transport=httpx.MockTransport(respond))
    with pytest.raises(InvalidIdentityTokenError):
        await verifier.verify(access_token(keypair))
    assert calls[1].method == "POST"
    assert calls[1].headers["authorization"].startswith("Basic ")


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def seed_memberships(db):
    client = Client(client_key="owned", display_name="Owned client")
    other = Client(client_key="other", display_name="Other client")
    subject = IdentitySubject(issuer="https://identity.example.test", subject="verified-user")
    collision = IdentitySubject(issuer="https://other.example.test", subject="verified-user")
    db.add_all([client, other, subject, collision])
    await db.flush()
    db.add_all(
        [
            ClientMembership(client_id=client.id, subject_id=subject.id, role="CONSULTANT"),
            ClientMembership(
                client_id=client.id, subject_id=subject.id, role="FUNCTIONAL_REVIEWER"
            ),
            ClientMembership(client_id=other.id, subject_id=collision.id, role="CLIENT_ADMIN"),
            PlatformRoleAssignment(subject_id=subject.id, role="ERP_CONFIGURATOR"),
        ]
    )
    await db.commit()
    return subject, client, other


@pytest.mark.asyncio
async def test_server_roles_override_token_roles_and_issuer_collision(keypair, db, monkeypatch):
    subject, client, other = await seed_memberships(db)
    monkeypatch.setattr(
        "app.security.identity.get_oidc_verifier", lambda settings: verifier_for(keypair)
    )
    actor = await get_current_identity(
        authorization="Bearer "
        + access_token(keypair, roles=["platform_admin"], client_ids=[other.id]),
        settings=configured(),
        db=db,
    )
    assert actor.subject_id == subject.id
    assert actor.roles == {"erp_configurator"}
    assert not actor.is_platform_admin
    assert actor.can_configure_erp and not actor.can_publish_erp
    assert actor.client_ids == {client.id}
    assert await identity_client_ids(db, actor) == {client.id}
    await ensure_client_access(db, actor, client.id, allowed_roles=["FUNCTIONAL_REVIEWER"])
    with pytest.raises(HTTPException) as error:
        await ensure_client_access(db, actor, other.id)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_claimed_clients_cannot_bypass_membership_or_role(db):
    _, client, _ = await seed_memberships(db)
    for actor in [
        Identity(
            user_id="unknown",
            issuer="https://identity.example.test",
            client_ids=frozenset({client.id}),
        ),
        Identity(user_id="unknown", is_fixture=True, client_ids=frozenset({client.id})),
        Identity(
            user_id="unknown",
            is_fixture=True,
            fixture_allow_claimed_clients=True,
            client_ids=frozenset({client.id}),
        ),
    ]:
        with pytest.raises(HTTPException):
            await ensure_client_access(db, actor, client.id, allowed_roles=["CLIENT_ADMIN"])


@pytest.mark.asyncio
async def test_inactive_subject_membership_and_client_deny_access(db):
    subject, client, _ = await seed_memberships(db)
    actor = Identity(user_id=subject.subject, issuer=subject.issuer)
    subject.status = "DISABLED"
    await db.flush()
    with pytest.raises(HTTPException):
        await ensure_client_access(db, actor, client.id)
    subject.status = "ACTIVE"
    client.status = "ARCHIVED"
    await db.flush()
    with pytest.raises(HTTPException):
        await ensure_client_access(db, actor, client.id)


@pytest.mark.asyncio
async def test_identity_projection_is_read_only_and_combines_active_roles(db):
    subject, client, _ = await seed_memberships(db)
    actor = Identity(user_id=subject.subject, issuer=subject.issuer, subject_id=subject.id)
    before = await db.scalar(select(func.count()).select_from(IdentitySubject))
    response = await current_identity(actor, db)
    assert response.model_dump()["clients"] == [
        {
            "id": client.id,
            "display_name": "Owned client",
            "roles": ["CONSULTANT", "FUNCTIONAL_REVIEWER"],
            "permissions": {
                "manage_environment": False,
                "create_request": True,
                "review_functional": True,
                "review_technical": False,
                "test": False,
            },
        }
    ]
    assert await db.scalar(select(func.count()).select_from(IdentitySubject)) == before
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.asyncio
async def test_runtime_shared_key_cannot_grant_admin_or_publication():
    actor = Identity(user_id="ordinary-user", roles=frozenset())
    with pytest.raises(HTTPException) as error:
        await require_erp_admin(
            "configured-shared-key", configured(erp_admin_api_key="configured-shared-key"), actor
        )
    assert error.value.status_code == 403
    with pytest.raises(HTTPException):
        await require_erp_publisher(
            Identity(user_id="editor", roles=frozenset({"platform_erp_configurator"}))
        )
    publisher = Identity(user_id="publisher", roles=frozenset({"platform_erp_publisher"}))
    assert await require_erp_publisher(publisher) == "publisher"
    assert not publisher.can_configure_erp and not publisher.is_platform_admin


@pytest.mark.asyncio
async def test_http_identity_is_authenticated_read_only_and_revocable(keypair, db, monkeypatch):
    subject, client, _ = await seed_memberships(db)
    monkeypatch.setattr(
        "app.security.identity.get_oidc_verifier", lambda settings: verifier_for(keypair)
    )

    async def session_dependency():
        yield db

    app = create_app(
        settings=configured(demo_mode=True, llm_provider="mock"),
        session_dependency=session_dependency,
    )
    headers = {"Authorization": "Bearer " + access_token(keypair, roles=["PLATFORM_ADMIN"])}
    before = await db.scalar(select(func.count()).select_from(IdentitySubject))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (await http.get("/api/identity/me")).status_code == 401
        me = await http.get("/api/identity/me", headers=headers)
        assert me.status_code == 200, me.text
        assert me.json()["capabilities"] == {
            "manage_clients": False,
            "configure_erp": True,
            "publish_erp": False,
        }
        assert [item["id"] for item in me.json()["clients"]] == [client.id]
        assert (await http.get("/api/erp-profiles/admin", headers=headers)).status_code == 200
        assert (
            await http.post(
                "/api/clients",
                headers=headers,
                json={"client_key": "denied", "display_name": "Denied"},
            )
        ).status_code == 403
        assert (
            await http.post("/api/erp-profiles/nonexistent/versions/1/publish", headers=headers)
        ).status_code == 403
        assert await db.scalar(select(func.count()).select_from(IdentitySubject)) == before
        assert not db.new and not db.dirty and not db.deleted
        subject.status = "DISABLED"
        await db.commit()
        assert (await http.get("/api/identity/me", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_development_empty_roles_and_memberships_use_server_ownership(db):
    client = Client(client_key="fixture-owned", display_name="Fixture client")
    subject = IdentitySubject(issuer="development", subject="fixture-user")
    db.add_all([client, subject])
    await db.flush()
    db.add(ClientMembership(client_id=client.id, subject_id=subject.id, role="CLIENT_ADMIN"))
    await db.commit()
    actor = await get_current_identity(
        x_dev_user_id="fixture-user",
        x_dev_roles="",
        x_dev_client_ids="foreign-id",
        settings=Settings(_env_file=None, app_env="test", auth_mode="development"),
        db=db,
    )
    assert not actor.roles and not actor.is_platform_admin
    assert actor.subject_id == subject.id
    assert actor.client_ids == actor.client_admin_ids == {client.id}
    assert db.info["authenticated_identity"] is actor
    assert db.info["erpfusion_tenant_context"].client_admin_ids == (client.id,)
    await ensure_client_access(db, actor, client.id, allowed_roles=["CLIENT_ADMIN"])


@pytest.mark.parametrize(
    "configuration",
    [
        {"password": "fixture-secret"},
        {"nested": {"api_token": "fixture-secret"}},
        {"assets": [{"client_secret": "fixture-secret"}]},
        {"url": "https://user:password@example.test"},
        {"url": "https://example.test?token=fixture-secret"},
    ],
)
def test_installation_configuration_rejects_credential_values(configuration):
    with pytest.raises(ValidationError):
        ERPInstallationCreate(
            erp_profile_id="profile",
            installation_key="x",
            display_name="ERP",
            configuration=configuration,
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:secret@example.test",
        "https://example.test?token=secret",
        "https://example.test#secret",
        "file:///private/customer.txt",
    ],
)
def test_environment_endpoint_rejects_credentials_and_non_http_urls(endpoint):
    with pytest.raises(ValidationError):
        ERPEnvironmentCreate(
            environment_key="sandbox", display_name="Sandbox", endpoint_url=endpoint
        )


def test_public_configuration_accepts_indirect_references_and_long_provider_subject():
    installation = ERPInstallationCreate(
        erp_profile_id="profile",
        installation_key="x",
        display_name=" ERP ",
        configuration={"credential_reference": "vault/item"},
    )
    assert installation.display_name == "ERP"
    assert installation.configuration == {"credential_reference": "vault/item"}
    membership = ClientMembershipCreate(subject_id=" " + "s" * 255 + " ", role="CONSULTANT")
    assert len(membership.subject_id) == 255
