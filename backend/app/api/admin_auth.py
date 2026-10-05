"""Platform role authorization for ERP configuration endpoints."""

import secrets

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.security.identity import Identity, get_current_identity


async def require_erp_admin(
    x_erp_admin_key: str | None = Header(default=None),
    settings: Settings | None = Depends(get_settings),
    identity: Identity | None = Depends(get_current_identity),
) -> str:
    """Authorize configuration using authenticated server role assignments.

    The shared key is accepted only by direct Python compatibility tests;
    FastAPI always supplies an Identity, preventing HTTP key authorization.
    """
    configured = settings if isinstance(settings, Settings) else get_settings()
    expected = configured.erp_admin_api_key
    actor = identity if isinstance(identity, Identity) else None
    if actor is not None and actor.can_configure_erp:
        return actor.user_id
    if (
        actor is None
        and not configured.is_production
        and expected
        and x_erp_admin_key
        and secrets.compare_digest(x_erp_admin_key, expected)
    ):
        return "erp-admin"
    if not expected and actor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ERP administration is disabled until ERP_ADMIN_API_KEY is configured.",
        )
    if actor is None and not x_erp_admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="ERP administrator access required"
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="ERP administrator role required"
    )


async def require_erp_publisher(identity: Identity = Depends(get_current_identity)) -> str:
    """Publication is a separate capability from editing ERP configuration."""
    if not isinstance(identity, Identity) or not identity.can_publish_erp:
        raise HTTPException(403, "ERP publisher role required")
    return identity.user_id


async def require_erp_reader(identity: Identity = Depends(get_current_identity)) -> str:
    """Both editors and publishers can inspect the versions they govern."""
    if not isinstance(identity, Identity) or not (
        identity.can_configure_erp or identity.can_publish_erp
    ):
        raise HTTPException(403, "ERP administration role required")
    return identity.user_id
