"""Schema declarativo de `config/providers.toml` (HU-S03 RF-01 a RF-07).

Los valores por defecto viven solo en este modulo y los heredan todos los
proveedores (RF-05).
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TIMEOUT_S = 2.0
DEFAULT_MAX_CONCURRENCY = 1000
DEFAULT_MAX_CONNECTIONS = 100


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AuthType(StrEnum):
    API_KEY = "api_key"
    BASIC = "basic"
    NONE = "none"


class AuthConfig(_Frozen):
    type: AuthType
    header: str | None = None
    secret_id: str | None = None

    @model_validator(mode="after")
    def _check_required(self) -> Self:
        if self.type is AuthType.API_KEY and not self.header:
            raise ValueError("auth.header es obligatorio para auth.type = 'api_key'")
        if self.type is not AuthType.NONE and not self.secret_id:
            raise ValueError(f"auth.secret_id es obligatorio para '{self.type}'")
        return self


class RateLimitAlgorithm(StrEnum):
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


class RateLimitConfig(_Frozen):
    enabled: bool = False
    requests: Annotated[int, Field(gt=0)] | None = None
    per_seconds: Annotated[float, Field(gt=0)] | None = None
    burst: Annotated[int, Field(gt=0)] | None = None
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    # Holgura que absorbe el jitter de red: el proveedor mide la llegada, no
    # el envio, y una rafaga que abre conexiones llega desfasada.
    safety_margin_s: Annotated[float, Field(ge=0, le=1)] = 0.0

    @model_validator(mode="after")
    def _check_quota(self) -> Self:
        if self.enabled and (self.requests is None or self.per_seconds is None):
            raise ValueError(
                "rate_limit.requests y rate_limit.per_seconds son obligatorios "
                "con rate_limit.enabled = true"
            )
        return self


class PricingConfig(_Frozen):
    taxes_included: bool = True
    tax_rate: Annotated[Decimal, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _check_tax_rate(self) -> Self:
        if not self.taxes_included and self.tax_rate is None:
            raise ValueError(
                "pricing.tax_rate es obligatorio con pricing.taxes_included = false"
            )
        return self


class BillingConfig(_Frozen):
    cost_per_request: Annotated[Decimal, Field(ge=0)] = Decimal("0")


class AmountFormatConfig(_Frozen):
    thousands_sep: str = ""
    decimal_sep: str = "."


class ParsingConfig(_Frozen):
    """Formatos declarados de fechas y montos (HU006 RF-09 a RF-11)."""

    date_formats: tuple[str, ...] = ("%Y-%m-%d",)
    amount: AmountFormatConfig = AmountFormatConfig()


class BusinessErrorCategory(StrEnum):
    NO_AVAILABILITY = "no_availability"
    QUERY = "query"
    AUTH = "auth"
    INTERNAL = "internal"


class BusinessErrorRule(_Frozen):
    """Ruta del campo + condicion (HU007 RF-03)."""

    path: str
    op: Literal["equals", "not_equals", "not_empty"]
    value: Any = None


class BusinessErrorConfig(_Frozen):
    rules: tuple[BusinessErrorRule, ...]
    code_paths: tuple[str, ...] = ("error.code",)
    codes: dict[str, BusinessErrorCategory] = {}


class ProviderConfig(_Frozen):
    id: Annotated[str, Field(min_length=1)]
    enabled: bool
    adapter: Annotated[str, Field(min_length=1)]
    base_url: Annotated[str, Field(pattern=r"^https?://")]
    auth: AuthConfig
    timeout_s: Annotated[float, Field(gt=0, le=MAX_TIMEOUT_S)] = MAX_TIMEOUT_S
    rate_limit: RateLimitConfig = RateLimitConfig()
    pricing: PricingConfig = PricingConfig()
    billing: BillingConfig = BillingConfig()
    parsing: ParsingConfig = ParsingConfig()
    business_errors: BusinessErrorConfig | None = None


class SearchConfig(_Frozen):
    """Presupuesto global de la consulta, a nivel de aplicacion (RF-07)."""

    timeout_s: Annotated[float, Field(gt=0, le=MAX_TIMEOUT_S)] = MAX_TIMEOUT_S
    max_concurrency: Annotated[int, Field(gt=0)] = DEFAULT_MAX_CONCURRENCY
    max_connections: Annotated[int, Field(gt=0)] = DEFAULT_MAX_CONNECTIONS


class AppConfig(_Frozen):
    search: SearchConfig = SearchConfig()
    providers: tuple[ProviderConfig, ...] = ()

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Self:
        seen: set[str] = set()
        duplicated: set[str] = set()
        for provider in self.providers:
            (duplicated if provider.id in seen else seen).add(provider.id)
        if duplicated:
            raise ValueError(f"ids de proveedor duplicados: {sorted(duplicated)}")
        return self

    @property
    def enabled_providers(self) -> tuple[ProviderConfig, ...]:
        return tuple(provider for provider in self.providers if provider.enabled)
