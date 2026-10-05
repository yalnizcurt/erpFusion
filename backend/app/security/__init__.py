"""Identity and authorization primitives for request-scoped access control."""

from app.security.access import ensure_client_access, get_authorized_project, resolved_identity
from app.security.identity import (
    Identity,
    IdentityConfigurationError,
    get_current_identity,
    identity_for_direct_call,
    require_authenticated_identity,
)

__all__ = [
    "Identity",
    "IdentityConfigurationError",
    "get_current_identity",
    "identity_for_direct_call",
    "require_authenticated_identity",
    "ensure_client_access",
    "get_authorized_project",
    "resolved_identity",
]
