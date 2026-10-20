"""Orquestacion paralela con presupuesto global (HU003).

DC-01: asyncio + niquests.AsyncSession; tiempo O(max latencia), memoria O(n).
DC-02: asyncio.Semaphore como limite global de concurrencia (k) junto al pool
de conexiones de la sesion compartida.
"""

import asyncio
import logging
import time
from collections.abc import Sequence

from availability_hotel.core.logging import get_logger, log_event
from availability_hotel.core.rate_limit import Clock
from availability_hotel.models import ProviderResult, ProviderStatus, SearchQuery
from availability_hotel.providers.base import BaseProvider

# Cada proveedor corta solo al llegar al deadline; la cancelacion del
# orquestador es una red de seguridad que se dispara apenas despues.
CANCEL_GRACE_S = 0.05

logger = get_logger("availability_hotel.orchestrator")


class Orchestrator:
    def __init__(
        self,
        providers: Sequence[BaseProvider],
        timeout_s: float,
        max_concurrency: int,
        clock: Clock = time.monotonic,
    ) -> None:
        self._providers = tuple(providers)
        self._timeout_s = timeout_s
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._clock = clock

    @property
    def providers(self) -> tuple[BaseProvider, ...]:
        return self._providers

    async def _call(
        self, provider: BaseProvider, query: SearchQuery, deadline: float
    ) -> ProviderResult:
        async with self._semaphore:
            return await provider.search(query, deadline)

    async def run(self, query: SearchQuery) -> list[ProviderResult]:
        """Devuelve un resultado por proveedor, en el orden de configuracion."""
        if not self._providers:
            log_event(logger, "no_enabled_providers", logging.WARNING)
            return []
        deadline = self._clock() + self._timeout_s
        tasks = [
            asyncio.create_task(self._call(provider, query, deadline))
            for provider in self._providers
        ]
        remaining = max(0.0, deadline - self._clock()) + CANCEL_GRACE_S
        _, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        if pending:
            # RF-09: esperar la cancelacion libera conexiones sin tareas huerfanas.
            await asyncio.gather(*pending, return_exceptions=True)
        return [
            self._result_of(provider, task)
            for provider, task in zip(self._providers, tasks, strict=True)
        ]

    @staticmethod
    def _result_of(provider: BaseProvider, task: asyncio.Task) -> ProviderResult:
        if task.cancelled():
            return ProviderResult(provider.id, ProviderStatus.TIMEOUT)
        if task.exception() is not None:  # pragma: no cover - BaseProvider las captura
            return ProviderResult(provider.id, ProviderStatus.HTTP_ERROR)
        return task.result()
