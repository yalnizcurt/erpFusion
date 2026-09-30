"""Optional deterministic validation adapters selected by profile configuration."""

from app.services.validation.engine import PLSQLValidator, SQLValidator
from app.models import ValidationCategory

VALIDATION_ADAPTERS = {
    "oracle_sql": (SQLValidator.validate, ValidationCategory.SQL),
    "oracle_plsql": (PLSQLValidator.validate, ValidationCategory.PLSQL),
}


def get_validation_adapter(adapter_name: str):
    configured_adapter = VALIDATION_ADAPTERS.get(adapter_name)
    if configured_adapter is None:
        raise ValueError(f"Validation adapter '{adapter_name}' is not installed.")
    return configured_adapter
