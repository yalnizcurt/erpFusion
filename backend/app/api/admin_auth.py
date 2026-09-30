"""Administrative API key authorization for ERP configuration endpoints."""

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_erp_admin(x_erp_admin_key: str | None = Header(default=None)) -> str:
    expected = get_settings().erp_admin_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ERP administration is disabled until ERP_ADMIN_API_KEY is configured.",
        )
    if not x_erp_admin_key or x_erp_admin_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ERP administrator access required")
    return "erp-admin"
