"""Consulta de entrada estandarizada (HU001 RF-01, RF-02)."""

from datetime import date
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

MAX_NIGHTS = 30
MAX_GUESTS = 10

Destination = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SearchQuery(BaseModel):
    """Entrada unica de `search`; tambien es el body de `POST /v1/availability`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    destino: Destination
    check_in: date
    check_out: date
    huespedes: Annotated[int, Field(ge=1, le=MAX_GUESTS, strict=True)]

    @field_validator("check_in")
    @classmethod
    def _check_in_not_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("check_in debe ser mayor o igual a hoy")
        return value

    @field_validator("check_out")
    @classmethod
    def _check_out_after_check_in(cls, value: date, info: ValidationInfo) -> date:
        check_in = info.data.get("check_in")
        if check_in is None:
            return value
        if value <= check_in:
            raise ValueError("check_out debe ser posterior a check_in")
        if (value - check_in).days > MAX_NIGHTS:
            raise ValueError(f"la estadia no puede superar {MAX_NIGHTS} noches")
        return value

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days
