"""Proveedor B: autenticacion basica, schema anidado, montos y fechas no
estandar, precios sin impuestos (HU006)."""

from collections.abc import Iterator
from typing import Any

from availability_hotel.core.extract import FormatError, as_list, get_path, parse_date
from availability_hotel.models import Discarded, Rate, SearchQuery
from availability_hotel.providers.base import BaseProvider, ProviderRequest
from availability_hotel.providers.registry import register_provider

REQUEST_DATE_FORMAT = "%d/%m/%Y"


@register_provider("provider_b")
class ProviderB(BaseProvider):
    def build_request(self, query: SearchQuery) -> ProviderRequest:
        return ProviderRequest(
            method="POST",
            path="/api/v2/disponibilidad",
            json={
                "Consulta": {
                    "CodigoDestino": query.destino,
                    "Estancia": {
                        "Entrada": query.check_in.strftime(REQUEST_DATE_FORMAT),
                        "Salida": query.check_out.strftime(REQUEST_DATE_FORMAT),
                    },
                    "Ocupacion": {"Adultos": query.huespedes},
                }
            },
        )

    def map_response(
        self, payload: Any, query: SearchQuery
    ) -> Iterator[Rate | Discarded]:
        """Recorre hoteles -> habitaciones -> tarifas en una pasada (DC-02)."""
        for hotel in as_list(get_path(payload, "Respuesta.Hoteles.Hotel")):
            hotel_name = get_path(hotel, "Nombre") or get_path(hotel, "Codigo")
            for room in as_list(get_path(hotel, "Habitaciones.Habitacion")):
                room_name = get_path(room, "Descripcion") or get_path(room, "Codigo")
                for tariff in as_list(get_path(room, "Tarifas.Tarifa")):
                    yield self._map_tariff(hotel_name, room_name, tariff, query)

    def _map_tariff(
        self, hotel: Any, room: Any, tariff: Any, query: SearchQuery
    ) -> Rate | Discarded:
        amount = get_path(tariff, "Importe.Valor")
        if amount in (None, ""):
            return Discarded("missing_amount", f"{hotel}/{room}")
        formats = self.config.parsing.date_formats
        try:
            check_in = parse_date(get_path(tariff, "Periodo.Desde"), formats)
            check_out = parse_date(get_path(tariff, "Periodo.Hasta"), formats)
        except FormatError as exc:
            return Discarded("invalid_date", str(exc))
        if (check_in, check_out) != (query.check_in, query.check_out):
            return Discarded("stay_mismatch", f"{check_in}..{check_out}")
        return self.make_rate(hotel, room, amount, get_path(tariff, "Importe.Divisa"))
