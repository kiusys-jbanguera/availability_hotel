"""Contrato comun de proveedor: metodo plantilla (HU002 RF-01, RF-06, RF-07)."""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar, Protocol

import niquests

from availability_hotel.config.schema import ProviderConfig
from availability_hotel.core.extract import AmountParser, FormatError
from availability_hotel.core.logging import (
    correlation_id_var,
    get_logger,
    log_event,
    truncate,
)
from availability_hotel.core.rate_limit import (
    Clock,
    RateLimiter,
    parse_retry_after,
)
from availability_hotel.models import (
    Discarded,
    ProviderResult,
    ProviderStatus,
    Rate,
    SearchQuery,
)
from availability_hotel.providers.auth import AuthStrategy
from availability_hotel.providers.business_errors import check_business_error
from availability_hotel.providers.errors import (
    ProviderError,
    ProviderHttpError,
    ProviderNoAvailability,
    ProviderParseError,
    ProviderRateLimited,
    ProviderTimeout,
)

CENTS = Decimal("0.01")
INVALID_JSON: Any = object()
IDEMPOTENCY_HEADER = "idempotency-key"
CORRELATION_HEADER = "X-Correlation-ID"

logger = get_logger("availability_hotel.providers")


class HttpSession(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    method: str
    path: str
    params: Mapping[str, Any] | None = None
    json: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    status_code: int
    headers: Mapping[str, str]
    payload: Any
    text: str


@dataclass(slots=True)
class _CallState:
    """Estado local de una sola llamada; no se comparte entre consultas."""

    stage: str = "prepare"
    sent: bool = False
    http_status: int | None = None
    idempotency_key: str | None = None


def _decode(body: bytes | None) -> tuple[Any, str]:
    text = (body or b"").decode("utf-8", errors="replace")
    try:
        return json.loads(text, parse_float=Decimal), text
    except ValueError:
        return INVALID_JSON, text


class BaseProvider(ABC):
    """Flujo comun; los adaptadores implementan solo los puntos de variacion."""

    required_headers: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        config: ProviderConfig,
        auth: AuthStrategy,
        session: HttpSession,
        rate_limiter: RateLimiter,
        clock: Clock = time.monotonic,
    ) -> None:
        self.config = config
        self.auth = auth
        self.session = session
        self.rate_limiter = rate_limiter
        self.clock = clock
        self.amount_parser = AmountParser(
            config.parsing.amount.thousands_sep, config.parsing.amount.decimal_sep
        )

    @property
    def id(self) -> str:
        return self.config.id

    # Puntos de variacion (HU002 RF-02) ---------------------------------------

    @abstractmethod
    def build_request(self, query: SearchQuery) -> ProviderRequest:
        """Traduce la consulta HU001 al request del proveedor."""

    @abstractmethod
    def map_response(
        self, payload: Any, query: SearchQuery
    ) -> Iterable[Rate | Discarded]:
        """Traduce el payload al modelo HU001; los nodos invalidos son Discarded."""

    def extra_headers(self) -> dict[str, str]:
        return {}

    def detect_error(self, response: ProviderResponse) -> None:
        """Clasifica errores HTTP y, si hay reglas declaradas, de negocio."""
        status = response.status_code
        if status == 429:
            raise ProviderRateLimited(
                "HTTP 429",
                retry_after=parse_retry_after(response.headers.get("Retry-After")),
            )
        if status in (401, 403):
            raise ProviderHttpError(
                f"HTTP {status}", error_code="AUTH", log_level=logging.ERROR
            )
        if not 200 <= status < 300:
            raise ProviderHttpError(f"HTTP {status}", error_code=f"HTTP_{status}")
        rules = self.config.business_errors
        if rules is not None and response.payload is not INVALID_JSON:
            check_business_error(rules, response.payload)

    # Utilidades para adaptadores (DRY) ---------------------------------------

    def make_rate(
        self, hotel: Any, room: Any, amount: Any, currency: Any
    ) -> Rate | Discarded:
        """Construye la oferta final sumando impuestos si el proveedor no los
        incluye (HU006 RF-13, RF-14): ROUND_HALF_UP a 2 decimales."""
        try:
            net = self.amount_parser.parse(amount)
        except FormatError as exc:
            return Discarded("invalid_amount", str(exc))
        pricing = self.config.pricing
        price = net
        if not pricing.taxes_included:
            if pricing.tax_rate is None:  # pragma: no cover - lo impide el schema
                return Discarded("missing_tax_rate")
            price = net + (net * pricing.tax_rate).quantize(CENTS, ROUND_HALF_UP)
        return Rate(
            hotel=str(hotel).strip() if hotel is not None else "",
            room=str(room).strip() if room is not None else "",
            price=price.quantize(CENTS, ROUND_HALF_UP),
            currency=str(currency or "").strip().upper(),
            provider=self.id,
        )

    # Flujo comun ---------------------------------------------------------------

    async def search(self, query: SearchQuery, deadline: float) -> ProviderResult:
        """Nunca lanza excepciones salvo la cancelacion del orquestador (RF-07)."""
        started = self.clock()
        state = _CallState()
        level, exc_info, error_code = logging.INFO, False, None
        rates: tuple[Rate, ...] = ()
        status = ProviderStatus.OK
        try:
            rates = await self._execute(query, deadline, state)
        except ProviderNoAvailability:
            pass
        except ProviderError as exc:
            status, error_code, level = exc.status, exc.error_code, exc.log_level
            if isinstance(exc, ProviderRateLimited) and exc.retry_after:
                self.rate_limiter.block_for(exc.retry_after)
        except TimeoutError, niquests.exceptions.Timeout:
            status, error_code, level = ProviderStatus.TIMEOUT, None, logging.WARNING
        except niquests.exceptions.RequestException as exc:
            status, level = ProviderStatus.HTTP_ERROR, logging.WARNING
            error_code = type(exc).__name__
        except asyncio.CancelledError:
            self._log(
                self._result(ProviderStatus.TIMEOUT, state, started), logging.WARNING
            )
            raise
        except Exception as exc:
            status = (
                ProviderStatus.PARSE_ERROR
                if state.stage == "mapping"
                else ProviderStatus.HTTP_ERROR
            )
            level, exc_info, error_code = logging.ERROR, True, type(exc).__name__
        result = self._result(status, state, started, rates, error_code)
        self._log(result, level, exc_info)
        return result

    async def _execute(
        self, query: SearchQuery, deadline: float, state: _CallState
    ) -> tuple[Rate, ...]:
        if deadline - self.clock() <= 0:
            raise ProviderTimeout("presupuesto agotado antes de enviar")
        if not await self.rate_limiter.acquire(deadline):
            raise ProviderRateLimited("sin cupo local de rate limit; no se envia")
        request = self.build_request(query)
        headers = {
            **self.auth.headers(),
            **self.extra_headers(),
            **request.headers,
        }
        correlation_id = correlation_id_var.get()
        if correlation_id:
            headers[CORRELATION_HEADER] = correlation_id
        state.idempotency_key = headers.get(IDEMPOTENCY_HEADER)
        missing = [name for name in self.required_headers if not headers.get(name)]
        if missing:
            raise RuntimeError(f"request sin headers obligatorios: {missing}")
        timeout = min(self.config.timeout_s, deadline - self.clock())
        if timeout <= 0:
            raise ProviderTimeout("presupuesto agotado antes de enviar")
        state.stage = "http"
        async with asyncio.timeout(timeout):
            state.sent = True
            raw = await self.session.request(
                request.method,
                self.config.base_url.rstrip("/") + request.path,
                params=request.params,
                json=request.json,
                headers=headers,
                timeout=timeout,
            )
        state.http_status = raw.status_code
        state.stage = "detect"
        payload, text = _decode(raw.content)
        response = ProviderResponse(raw.status_code, raw.headers, payload, text)
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                "provider_response",
                logging.DEBUG,
                provider_id=self.id,
                http_status=raw.status_code,
                body=truncate(text),
            )
        self.detect_error(response)
        if payload is INVALID_JSON:
            raise ProviderParseError("respuesta 2xx sin JSON valido")
        state.stage = "mapping"
        rates = self._collect(self.map_response(payload, query))
        if self.clock() > deadline:
            raise ProviderTimeout("el mapeo excedio el presupuesto")
        return rates

    def _collect(self, items: Iterable[Rate | Discarded]) -> tuple[Rate, ...]:
        valid: list[Rate] = []
        discarded = 0
        for item in items:
            reason = (
                item.reason if isinstance(item, Discarded) else item.invalid_reason()
            )
            if reason is None:
                valid.append(item)
                continue
            discarded += 1
            log_event(
                logger,
                "offer_discarded",
                logging.DEBUG,
                provider_id=self.id,
                reason=reason,
                detail=getattr(item, "detail", ""),
            )
        if not valid and discarded:
            raise ProviderParseError(
                f"{discarded} ofertas invalidas", error_code="ALL_OFFERS_INVALID"
            )
        return tuple(valid)

    def _result(
        self,
        status: ProviderStatus,
        state: _CallState,
        started: float,
        rates: tuple[Rate, ...] = (),
        error_code: str | None = None,
    ) -> ProviderResult:
        cost = self.config.billing.cost_per_request if state.sent else Decimal("0")
        return ProviderResult(
            provider_id=self.id,
            status=status,
            rates=rates,
            latency_ms=round((self.clock() - started) * 1000, 1),
            http_status=state.http_status,
            error_code=error_code,
            billable=cost > 0,
            cost=cost,
            idempotency_key=state.idempotency_key,
        )

    def _log(self, result: ProviderResult, level: int, exc_info: bool = False) -> None:
        log_event(
            logger,
            "provider_call",
            level,
            exc_info=exc_info,
            provider_id=result.provider_id,
            status=result.status,
            http_status=result.http_status,
            latency_ms=result.latency_ms,
            results_count=len(result.rates),
            error_code=result.error_code,
            billable=result.billable,
            idempotency_key=result.idempotency_key,
        )
