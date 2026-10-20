"""Proveedor C: API key y errores de negocio dentro de HTTP 200 (HU007).

La deteccion de errores es declarativa (`business_errors` en providers.toml) y
la aplica `BaseProvider.detect_error`; el adaptador solo traduce request y
payload.
"""

from collections.abc import Iterator
from typing import Any

from availability_hotel.core.extract import as_list, get_path
from availability_hotel.models import Discarded, Rate, SearchQuery
from availability_hotel.providers.base import BaseProvider, ProviderRequest
from availability_hotel.providers.registry import register_provider


@register_provider("provider_c")
class ProviderC(BaseProvider):
    def build_request(self, query: SearchQuery) -> ProviderRequest:
        return ProviderRequest(
            method="POST",
            path="/hotels/search",
            json={
                "city_code": query.destino,
                "stay": {
                    "check_in": query.check_in.isoformat(),
                    "check_out": query.check_out.isoformat(),
                },
                "guests": query.huespedes,
            },
        )

    def map_response(
        self, payload: Any, query: SearchQuery
    ) -> Iterator[Rate | Discarded]:
        for item in as_list(get_path(payload, "data.results")):
            yield self.make_rate(
                hotel=get_path(item, "hotel.name") or get_path(item, "hotel.id"),
                room=get_path(item, "room.description") or get_path(item, "room.code"),
                amount=get_path(item, "price.amount"),
                currency=get_path(item, "price.currency"),
            )
