"""Logging estructurado JSON, unico punto de configuracion (HU-S04)."""

import atexit
import json
import logging
import logging.handlers
import queue
import sys
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TextIO

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

REDACTED = "***"
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "x-api-key",
        "authorization",
        "password",
        "secret",
        "secret_string",
        "token",
        "username",
        "aws_secret_access_key",
    }
)
MAX_DEBUG_BODY_CHARS = 512
_THIRD_PARTY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi")

_listener: logging.handlers.QueueListener | None = None


def redact(value: Any) -> Any:
    """Reemplaza recursivamente los valores de claves sensibles (RNF-01)."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if str(key).lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def truncate(text: str, limit: int = MAX_DEBUG_BODY_CHARS) -> str:
    """Recorta cuerpos grandes antes de registrarlos en DEBUG."""
    return text if len(text) <= limit else f"{text[:limit]}...<truncated>"


def _default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    return repr(value)


class JsonFormatter(logging.Formatter):
    """Una linea JSON por evento con correlation_id y campos redactados."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            payload["correlation_id"] = correlation_id
        payload.update(redact(getattr(record, "fields", None) or {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=_default, ensure_ascii=False)


class ContextFilter(logging.Filter):
    """Inyecta el correlation_id del contexto antes de encolar el registro."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "correlation_id", None) is None:
            record.correlation_id = correlation_id_var.get()
        return True


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Configura el logger raiz con un QueueHandler no bloqueante hacia stderr."""
    global _listener
    shutdown_logging()
    logging.raiseExceptions = False
    target = logging.StreamHandler(stream or sys.stderr)
    target.setFormatter(logging.Formatter("%(message)s"))
    log_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setFormatter(JsonFormatter())
    queue_handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(queue_handler)
    root.setLevel(level.upper())
    for name in _THIRD_PARTY_LOGGERS:
        third_party = logging.getLogger(name)
        third_party.handlers.clear()
        third_party.setLevel(logging.NOTSET)
        third_party.propagate = True
    _listener = logging.handlers.QueueListener(log_queue, target)
    _listener.start()


def shutdown_logging() -> None:
    """Vacia la cola de logs pendientes y detiene el hilo escritor."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


atexit.register(shutdown_logging)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Emite un evento estructurado; los campos viajan como JSON de primer nivel."""
    logger.log(level, event, exc_info=exc_info, extra={"fields": fields})
