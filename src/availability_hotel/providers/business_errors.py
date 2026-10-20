"""Deteccion declarativa de errores de negocio en respuestas 2xx (HU007)."""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from availability_hotel.config.schema import (
    BusinessErrorCategory,
    BusinessErrorConfig,
    BusinessErrorRule,
)
from availability_hotel.core.extract import MISSING, get_path
from availability_hotel.providers.errors import (
    ProviderBusinessError,
    ProviderNoAvailability,
)

UNKNOWN_CODE = "UNKNOWN"

_OPERATORS: Mapping[str, Callable[[Any, Any], bool]] = {
    "equals": lambda actual, expected: actual is not MISSING and actual == expected,
    "not_equals": lambda actual, expected: actual is not MISSING and actual != expected,
    "not_empty": lambda actual, expected: actual is not MISSING and bool(actual),
}

_LOG_LEVELS: Mapping[BusinessErrorCategory | None, int] = {
    BusinessErrorCategory.QUERY: logging.WARNING,
    BusinessErrorCategory.AUTH: logging.ERROR,
    BusinessErrorCategory.INTERNAL: logging.ERROR,
    None: logging.WARNING,
}


def _matches(rule: BusinessErrorRule, payload: Any) -> bool:
    return _OPERATORS[rule.op](get_path(payload, rule.path, MISSING), rule.value)


def _error_code(config: BusinessErrorConfig, payload: Any) -> str:
    for path in config.code_paths:
        code = get_path(payload, path)
        if code not in (None, ""):
            return str(code)
    return UNKNOWN_CODE


def check_business_error(config: BusinessErrorConfig, payload: Any) -> None:
    """Lanza la excepcion correspondiente si alguna regla indica error.

    O(r * d), r = reglas y d = profundidad de cada ruta (RNF-01).
    """
    if not any(_matches(rule, payload) for rule in config.rules):
        return
    code = _error_code(config, payload)
    category = config.codes.get(code)
    if category is BusinessErrorCategory.NO_AVAILABILITY:
        raise ProviderNoAvailability(code)
    error_code = "AUTH" if category is BusinessErrorCategory.AUTH else code
    raise ProviderBusinessError(
        f"error de negocio {code}",
        error_code=error_code,
        log_level=_LOG_LEVELS[category],
    )
