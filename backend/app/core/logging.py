"""Content-minimizing operational logging; engineering evidence belongs in controlled storage."""

import logging
import os
import re
from urllib.parse import unquote, urlsplit

from app.config import Settings

_TOKEN = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9+/._=:-]+")
_DATABASE_CREDENTIALS = re.compile(r"([a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|password|client[_-]?secret|authorization|"
    r"access[_-]?token|refresh[_-]?token|private[_-]?key)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_CONTENT_ASSIGNMENT = re.compile(
    r"(?i)[\"']?\b(?:system_prompt|user_prompt|business_requirement|schema_context|"
    r"generated_content|raw_response)[\"']?\s*[:=].*",
    re.S,
)


def redact_text(message: str, secrets: tuple[str, ...] = ()) -> str:
    """Defensive scrubbing supplements the rule that content must not be logged."""
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        message = message.replace(secret, "[redacted]")
    message = _DATABASE_CREDENTIALS.sub(r"\1[redacted]@", message)
    message = _TOKEN.sub(lambda match: f"{match.group(1)} [redacted]", message)
    message = _SECRET_ASSIGNMENT.sub(r"\1[redacted]", message)
    message = _CONTENT_ASSIGNMENT.sub("content=[redacted]", message)
    return message


class OperationalLogFilter(logging.Filter):
    """Keep secrets, provider error bodies, and exception values out of normal logs."""

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.exc_info and record.exc_info[0]:
            message = f"{message} exception_type={record.exc_info[0].__name__}"
        record.msg = redact_text(message, self.secrets)
        record.args = ()
        # Exception text can include SQL parameters, source documents, or provider bodies.
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_logging(settings: Settings) -> None:
    """Configure local operational logs without external exporters or telemetry SDKs."""
    credentials: tuple[str, ...] = (
        settings.groq_api_key,
        settings.erp_admin_api_key,
        settings.oidc_introspection_client_secret,
        settings.aws_access_key_id,
        settings.aws_secret_access_key,
        os.environ.get("AWS_ACCESS_KEY_ID", ""),
        os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        os.environ.get("AWS_SESSION_TOKEN", ""),
    )
    try:
        database_password = urlsplit(settings.database_url).password
    except ValueError:
        database_password = None
    if database_password:
        credentials += (database_password, unquote(database_password))
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    root.setLevel(settings.log_level)
    # SDK debug records can contain signed requests and uploaded file bytes.
    for sdk_logger in ("boto3", "botocore", "s3transfer"):
        logging.getLogger(sdk_logger).setLevel(logging.WARNING)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    handlers = set(root.handlers)
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            handlers.update(logger.handlers)
    for handler in handlers:
        handler_credentials = set(credentials)
        for existing in list(handler.filters):
            if isinstance(existing, OperationalLogFilter):
                handler_credentials.update(existing.secrets)
                handler.removeFilter(existing)
        handler.addFilter(OperationalLogFilter(tuple(sorted(handler_credentials))))
        handler.setFormatter(formatter)
