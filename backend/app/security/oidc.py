"""Verify OIDC JWT access tokens against a pinned provider and bounded JWKS cache."""

from __future__ import annotations

import asyncio
import json
import math
import time
from functools import lru_cache
from typing import Any

import httpx
import jwt
from jwt import PyJWK

from app.config import Settings

MAX_PROVIDER_RESPONSE_BYTES = 262_144
MAX_JWKS_KEYS = 32
MAX_TOKEN_BYTES = 16_384


class InvalidIdentityTokenError(Exception):
    """The token does not establish a verified identity."""


class IdentityProviderUnavailableError(Exception):
    """The configured identity provider could not be safely contacted."""


class OIDCVerifier:
    """Asymmetric JWT verifier; all network destinations come from server settings."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        self._keys: dict[tuple[str, str], PyJWK] = {}
        self._expires_at = 0.0
        self._last_refresh = float("-inf")
        self._lock = asyncio.Lock()

    async def _provider_json(self, url: str, *, token: str | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.oidc_http_timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
                trust_env=False,
            ) as client:
                request = client.build_request("GET", url)
                if token is not None:
                    request = client.build_request(
                        "POST",
                        url,
                        data={"token": token, "token_type_hint": "access_token"},
                    )
                    credentials = httpx.BasicAuth(
                        self.settings.oidc_introspection_client_id,
                        self.settings.oidc_introspection_client_secret,
                    )
                    request = next(credentials.auth_flow(request))
                async with client.stream(
                    request.method,
                    request.url,
                    headers=request.headers,
                    content=request.content,
                ) as response:
                    if response.status_code != 200:
                        raise IdentityProviderUnavailableError()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_PROVIDER_RESPONSE_BYTES:
                            raise IdentityProviderUnavailableError()
                        chunks.append(chunk)
            value = json.loads(b"".join(chunks))
            if not isinstance(value, dict):
                raise IdentityProviderUnavailableError()
            return value
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise IdentityProviderUnavailableError() from exc

    async def _signing_key(self, kid: str, algorithm: str) -> PyJWK:
        now = time.monotonic()
        if now < self._expires_at and (kid, algorithm) in self._keys:
            return self._keys[kid, algorithm]
        async with self._lock:
            now = time.monotonic()
            if now < self._expires_at and (kid, algorithm) in self._keys:
                return self._keys[kid, algorithm]
            # Bound unknown-kid refresh attempts, including failed provider calls.
            if now - self._last_refresh < 30:
                if now >= self._expires_at:
                    raise IdentityProviderUnavailableError()
                raise InvalidIdentityTokenError()
            self._last_refresh = now
            payload = await self._provider_json(self.settings.oidc_jwks_url)
            entries = payload.get("keys")
            if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_JWKS_KEYS:
                raise IdentityProviderUnavailableError()
            keys: dict[tuple[str, str], PyJWK] = {}
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("kid"), str):
                    continue
                key_id = entry["kid"]
                if not key_id or len(key_id) > 255 or entry.get("use", "sig") != "sig":
                    continue
                if "key_ops" in entry:
                    if not isinstance(entry["key_ops"], list):
                        raise IdentityProviderUnavailableError()
                    if "verify" not in entry["key_ops"]:
                        continue
                for allowed in self.settings.oidc_algorithms:
                    if entry.get("alg", allowed) != allowed:
                        continue
                    try:
                        key = PyJWK.from_dict(entry, algorithm=allowed)
                    except (jwt.PyJWTError, ValueError, TypeError):
                        continue
                    if key.key_type == "oct" or (key_id, allowed) in keys:
                        raise IdentityProviderUnavailableError()
                    keys[key_id, allowed] = key
            if not keys:
                raise IdentityProviderUnavailableError()
            self._keys = keys
            self._expires_at = time.monotonic() + self.settings.oidc_jwks_cache_seconds
            if (kid, algorithm) not in keys:
                raise InvalidIdentityTokenError()
            return keys[kid, algorithm]

    async def verify(self, token: str) -> dict[str, Any]:
        if self.settings.oidc_configuration_issues():
            raise IdentityProviderUnavailableError()
        if not token or len(token.encode()) > MAX_TOKEN_BYTES:
            raise InvalidIdentityTokenError()
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if (
                algorithm not in self.settings.oidc_algorithms
                or not isinstance(kid, str)
                or not kid
                or len(kid) > 255
                or header.get("crit")
            ):
                raise InvalidIdentityTokenError()
            key = await self._signing_key(kid, algorithm)
            audience_claim = self.settings.oidc_audience_claim
            required_claims = ["exp", "iat", "iss", audience_claim, "sub"]
            if self.settings.oidc_token_use:
                required_claims.append("token_use")
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[algorithm],
                audience=self.settings.oidc_audience if audience_claim == "aud" else None,
                issuer=self.settings.oidc_issuer,
                leeway=self.settings.oidc_clock_skew_seconds,
                options={"require": required_claims, "verify_aud": audience_claim == "aud"},
            )
            if (
                audience_claim != "aud"
                and claims.get(audience_claim) != self.settings.oidc_audience
            ):
                raise InvalidIdentityTokenError()
            if self.settings.oidc_token_use and (
                claims.get("token_use") != self.settings.oidc_token_use
            ):
                raise InvalidIdentityTokenError()
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
                raise InvalidIdentityTokenError()
            for claim in ("exp", "iat"):
                if (
                    not isinstance(claims[claim], (int, float))
                    or isinstance(claims[claim], bool)
                    or not math.isfinite(claims[claim])
                ):
                    raise InvalidIdentityTokenError()
            if claims["exp"] <= claims["iat"]:
                raise InvalidIdentityTokenError()
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise InvalidIdentityTokenError() from exc
        if self.settings.oidc_introspection_url:
            session = await self._provider_json(self.settings.oidc_introspection_url, token=token)
            if session.get("active") is not True:
                raise InvalidIdentityTokenError()
            if session.get("sub", claims["sub"]) != claims["sub"]:
                raise InvalidIdentityTokenError()
        return claims


@lru_cache(maxsize=8)
def _cached_verifier(settings_json: str) -> OIDCVerifier:
    return OIDCVerifier(Settings.model_validate_json(settings_json))


def get_oidc_verifier(settings: Settings) -> OIDCVerifier:
    """Cache at most eight configured providers; configuration is never logged."""
    return _cached_verifier(
        settings.model_dump_json(
            include={name for name in Settings.model_fields if name.startswith("oidc_")}
        )
    )
