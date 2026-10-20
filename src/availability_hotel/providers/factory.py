"""Instanciacion de proveedores habilitados a partir de registro + configuracion."""

import time
from collections.abc import Mapping

from availability_hotel.config.loader import LoadedConfig
from availability_hotel.config.schema import RateLimitAlgorithm, RateLimitConfig
from availability_hotel.core.rate_limit import (
    Clock,
    RateLimiter,
    SlidingWindowLimiter,
    TokenBucketLimiter,
)
from availability_hotel.providers.auth import build_auth
from availability_hotel.providers.base import BaseProvider, HttpSession
from availability_hotel.providers.registry import registry as default_registry


def build_rate_limiter(config: RateLimitConfig, clock: Clock) -> RateLimiter:
    """Un limitador independiente por proveedor (HU004 RF-03)."""
    if not config.enabled:
        return RateLimiter(clock)
    if config.algorithm is RateLimitAlgorithm.TOKEN_BUCKET:
        return TokenBucketLimiter(
            config.requests, config.per_seconds, config.burst, clock
        )
    return SlidingWindowLimiter(
        config.requests, config.per_seconds + config.safety_margin_s, clock
    )


def build_providers(
    loaded: LoadedConfig,
    session: HttpSession,
    registry: Mapping[str, type[BaseProvider]] = default_registry,
    clock: Clock = time.monotonic,
) -> tuple[BaseProvider, ...]:
    """Los proveedores deshabilitados no se instancian (HU-S03 RF-06)."""
    return tuple(
        registry[config.adapter](
            config=config,
            auth=build_auth(config.auth, loaded.secrets.get(config.id)),
            session=session,
            rate_limiter=build_rate_limiter(config.rate_limit, clock),
            clock=clock,
        )
        for config in loaded.app.enabled_providers
    )
