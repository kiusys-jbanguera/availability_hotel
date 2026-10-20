"""Controlador MVC: unico punto de entrada a la logica de negocio (HU008)."""

import time
import uuid
from datetime import date
from decimal import Decimal

from availability_hotel.controllers.orchestrator import Orchestrator
from availability_hotel.core.logging import correlation_id_var, get_logger, log_event
from availability_hotel.core.rate_limit import Clock
from availability_hotel.models import (
    ProviderResult,
    ProviderStatus,
    SearchOutcome,
    SearchQuery,
)
from availability_hotel.views import SearchResponse, render_search

logger = get_logger("availability_hotel.search")


def _summary(results: list[ProviderResult], elapsed_ms: float) -> dict[str, object]:
    """Totales de `search_completed` (HU-S04 RF-04, HU005 RF-08, HU006 RF-05)."""
    timeouts = [r.provider_id for r in results if r.status is ProviderStatus.TIMEOUT]
    return {
        "providers_queried": len(results),
        "responded_in_time": sum(r.status is ProviderStatus.OK for r in results),
        "excluded_by_timeout": len(timeouts),
        "timeout_providers": timeouts,
        "with_error": sum(
            r.failed and r.status is not ProviderStatus.TIMEOUT for r in results
        ),
        "results_count": sum(len(r.rates) for r in results),
        "latency_ms": round(elapsed_ms, 1),
        "billable_requests": sum(r.billable for r in results),
        "estimated_cost": sum((r.cost for r in results), Decimal("0")),
        "provider_status": {r.provider_id: r.status.value for r in results},
    }


class SearchService:
    """Servicio asincrono puro; no depende de FastAPI (RF-03, RF-04)."""

    def __init__(self, orchestrator: Orchestrator, clock: Clock = time.monotonic):
        self._orchestrator = orchestrator
        self._clock = clock

    async def search(
        self, destino: str, check_in: date, check_out: date, huespedes: int
    ) -> SearchResponse:
        query = SearchQuery(
            destino=destino, check_in=check_in, check_out=check_out, huespedes=huespedes
        )
        search_id = str(uuid.uuid4())
        token = correlation_id_var.set(str(uuid.uuid4()))
        started = self._clock()
        try:
            log_event(
                logger,
                "search_started",
                search_id=search_id,
                destino=query.destino,
                check_in=query.check_in.isoformat(),
                check_out=query.check_out.isoformat(),
                huespedes=query.huespedes,
                providers=[p.id for p in self._orchestrator.providers],
            )
            results = await self._orchestrator.run(query)
            outcome = SearchOutcome.from_results(results)
            elapsed_ms = (self._clock() - started) * 1000
            log_event(
                logger,
                "search_completed",
                search_id=search_id,
                **_summary(results, elapsed_ms),
            )
            return render_search(outcome)
        finally:
            correlation_id_var.reset(token)
