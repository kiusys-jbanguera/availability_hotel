"""Extraccion por ruta y parsers declarativos de montos y fechas (HU006, HU007)."""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MISSING = object()


def get_path(payload: Any, path: str, default: Any = None) -> Any:
    """Lee `a.b.0.c` recorriendo dicts y listas; O(d) con d = profundidad."""
    current = payload
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, str):
            try:
                current = current[int(part)]
            except ValueError, IndexError:
                return default
        else:
            return default
    return current


def as_list(value: Any) -> list[Any]:
    """Normaliza nodos que pueden venir como objeto unico, lista o ausentes."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class FormatError(ValueError):
    """El valor no coincide con ninguno de los formatos declarados."""


def parse_date(value: Any, formats: Iterable[str]) -> date:
    """Prueba los formatos declarados en orden; O(f) con f = formatos (DC-01)."""
    text = str(value).strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise FormatError(f"fecha '{text}' no coincide con los formatos declarados")


class AmountParser:
    """Convierte montos con separadores declarados a Decimal, sin heuristicas."""

    def __init__(self, thousands_sep: str = "", decimal_sep: str = ".") -> None:
        self.thousands_sep = thousands_sep
        self.decimal_sep = decimal_sep
        integer = r"\d+"
        if thousands_sep:
            sep = re.escape(thousands_sep)
            integer = rf"(?:\d{{1,3}}(?:{sep}\d{{3}})+|\d+)"
        self._pattern = re.compile(rf"^-?{integer}(?:{re.escape(decimal_sep)}\d+)?$")

    def parse(self, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return Decimal(value)
        text = str(value).strip()
        if not self._pattern.match(text):
            raise FormatError(f"monto '{text}' no coincide con el formato declarado")
        if self.thousands_sep:
            text = text.replace(self.thousands_sep, "")
        try:
            return Decimal(text.replace(self.decimal_sep, "."))
        except InvalidOperation as exc:  # pragma: no cover - el regex lo impide
            raise FormatError(f"monto '{text}' invalido") from exc
