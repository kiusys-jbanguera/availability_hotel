"""Adaptadores por proveedor y contrato comun (HU002, HU005-HU007).

Los adaptadores se registran mediante una lista explicita de imports (HU002
P-01: trazabilidad) y el decorador `@register_provider`.
"""

from availability_hotel.providers.adapters import (  # noqa: F401
    provider_a,
    provider_b,
    provider_c,
)
from availability_hotel.providers.base import BaseProvider
from availability_hotel.providers.factory import build_providers
from availability_hotel.providers.registry import registry

__all__ = ["BaseProvider", "build_providers", "registry"]
