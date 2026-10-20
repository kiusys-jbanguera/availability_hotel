"""Tarifa normalizada, resultado por proveedor y resultado de la busqueda."""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class ProviderStatus(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    BUSINESS_ERROR = "business_error"
    HTTP_ERROR = "http_error"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"


FAILURE_REASONS = frozenset(
    {
        ProviderStatus.TIMEOUT,
        ProviderStatus.RATE_LIMITED,
        ProviderStatus.BUSINESS_ERROR,
        ProviderStatus.HTTP_ERROR,
        ProviderStatus.PARSE_ERROR,
    }
)


@dataclass(frozen=True, slots=True)
class Rate:
    """Oferta interna; `price` es el precio final con impuestos (RF-05, RF-06)."""

    hotel: str
    room: str
    price: Decimal
    currency: str
    provider: str

    def invalid_reason(self) -> str | None:
        """Motivo por el que la oferta no puede publicarse, o None si es valida."""
        if not str(self.hotel or "").strip():
            return "missing_hotel"
        if not str(self.room or "").strip():
            return "missing_room"
        if not isinstance(self.price, Decimal) or not self.price.is_finite():
            return "invalid_price"
        if self.price <= 0:
            return "non_positive_price"
        if not CURRENCY_PATTERN.match(str(self.currency or "")):
            return "invalid_currency"
        return None


@dataclass(frozen=True, slots=True)
class Discarded:
    """Nodo del payload que el adaptador no pudo convertir en oferta."""

    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Resultado de una llamada a proveedor (HU002 RF-05)."""

    provider_id: str
    status: ProviderStatus
    rates: tuple[Rate, ...] = ()
    latency_ms: float = 0.0
    http_status: int | None = None
    error_code: str | None = None
    billable: bool = False
    cost: Decimal = Decimal("0")
    idempotency_key: str | None = None

    @property
    def failed(self) -> bool:
        return self.status in FAILURE_REASONS


@dataclass(frozen=True, slots=True)
class FailedProvider:
    provider: str
    reason: ProviderStatus


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Salida de dominio previa a la serializacion en `views/`."""

    results: tuple[Rate, ...] = ()
    failed_providers: tuple[FailedProvider, ...] = field(default_factory=tuple)

    @classmethod
    def from_results(cls, provider_results: list[ProviderResult]) -> "SearchOutcome":
        rates = [rate for result in provider_results for rate in result.rates]
        # DC-01: sorted O(n log n); agrupa por moneda y ordena por precio final.
        rates.sort(key=lambda rate: (rate.currency, rate.price, rate.provider))
        failed = tuple(
            FailedProvider(result.provider_id, result.status)
            for result in provider_results
            if result.failed
        )
        return cls(results=tuple(rates), failed_providers=failed)
