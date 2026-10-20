"""Modelos de dominio estandarizados (HU001)."""

from availability_hotel.models.query import MAX_GUESTS, MAX_NIGHTS, SearchQuery
from availability_hotel.models.rate import (
    FAILURE_REASONS,
    Discarded,
    FailedProvider,
    ProviderResult,
    ProviderStatus,
    Rate,
    SearchOutcome,
)

__all__ = [
    "FAILURE_REASONS",
    "MAX_GUESTS",
    "MAX_NIGHTS",
    "Discarded",
    "FailedProvider",
    "ProviderResult",
    "ProviderStatus",
    "Rate",
    "SearchOutcome",
    "SearchQuery",
]
