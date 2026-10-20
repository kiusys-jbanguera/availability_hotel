"""Ensamblado de dependencias al arranque: configuracion, secretos, sesion
HTTP compartida, proveedores, orquestador y servicio."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import niquests

from availability_hotel.config import (
    ConfigError,
    Settings,
    build_secrets_client,
    load_config,
)
from availability_hotel.config.schema import SearchConfig
from availability_hotel.config.secrets import SecretsClient
from availability_hotel.controllers.orchestrator import Orchestrator
from availability_hotel.controllers.search_service import SearchService
from availability_hotel.core.logging import get_logger, log_event
from availability_hotel.providers import build_providers, registry

logger = get_logger("availability_hotel.runtime")

SecretsFactory = Callable[[Settings], SecretsClient]
SessionFactory = Callable[[SearchConfig, int], Any]


def default_session_factory(search: SearchConfig, providers: int) -> Any:
    """Una sola sesion con pool compartido entre consultas (HU003 RF-07)."""
    return niquests.AsyncSession(
        pool_connections=max(1, providers),
        pool_maxsize=search.max_connections,
        disable_http3=True,
    )


@dataclass(slots=True)
class Runtime:
    service: SearchService | None = None
    session: Any = None
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.service is not None

    async def aclose(self) -> None:
        if self.session is not None:
            await self.session.close()


async def build_runtime(
    settings: Settings,
    secrets_factory: SecretsFactory = build_secrets_client,
    session_factory: SessionFactory = default_session_factory,
) -> Runtime:
    """Un error de configuracion deja la app arriba pero no lista (HTTP 503)."""
    try:
        loaded = await asyncio.to_thread(
            load_config,
            settings.providers_config,
            registry,
            lambda: secrets_factory(settings),
        )
    except ConfigError as exc:
        log_event(logger, "config_error", logging.ERROR, error=str(exc))
        return Runtime(error=str(exc))
    session = session_factory(loaded.app.search, len(loaded.app.enabled_providers))
    providers = build_providers(loaded, session)
    orchestrator = Orchestrator(
        providers,
        timeout_s=loaded.app.search.timeout_s,
        max_concurrency=loaded.app.search.max_concurrency,
    )
    log_event(
        logger,
        "config_loaded",
        providers=[provider.id for provider in providers],
        disabled=[p.id for p in loaded.app.providers if not p.enabled],
        search_timeout_s=loaded.app.search.timeout_s,
    )
    return Runtime(service=SearchService(orchestrator), session=session)
