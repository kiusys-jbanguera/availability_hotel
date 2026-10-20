"""Proveedor A: REST/JSON plano, API key, idempotency-key y cobro por request
(HU005)."""

import uuid
from collections.abc import Iterator
from typing import Any

from availability_hotel.core.extract import as_list
from availability_hotel.models import Discarded, Rate, SearchQuery
from availability_hotel.providers.base import (
    IDEMPOTENCY_HEADER,
    BaseProvider,
    ProviderRequest,
    ProviderResponse,
)
from availability_hotel.providers.errors import ProviderHttpError
from availability_hotel.providers.registry import register_provider

IDEMPOTENCY_STATUSES = frozenset({409, 422})


@register_provider("provider_a")
class ProviderA(BaseProvider):
    required_headers = (IDEMPOTENCY_HEADER,)

    def build_request(self, query: SearchQuery) -> ProviderRequest:
        return ProviderRequest(
            method="GET",
            path="/v1/availability",
            params={
                "destination": query.destino,
                "checkin": query.check_in.isoformat(),
                "checkout": query.check_out.isoformat(),
                "adults": query.huespedes,
            },
        )

    def extra_headers(self) -> dict[str, str]:
        return {IDEMPOTENCY_HEADER: str(uuid.uuid4())}

    def detect_error(self, response: ProviderResponse) -> None:
        if response.status_code in IDEMPOTENCY_STATUSES:
            raise ProviderHttpError(
                f"HTTP {response.status_code}", error_code="IDEMPOTENCY"
            )
        super().detect_error(response)

    def map_response(
        self, payload: Any, query: SearchQuery
    ) -> Iterator[Rate | Discarded]:
        currency = payload.get("currency")
        for offer in as_list(payload.get("offers")):
            yield self.make_rate(
                hotel=offer.get("hotel_name") or offer.get("hotel_code"),
                room=offer.get("room_name") or offer.get("room_code"),
                amount=offer.get("total_price"),
                currency=offer.get("currency") or currency,
            )
