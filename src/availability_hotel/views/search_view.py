"""Serializacion de la respuesta publica estandarizada (HU001 RF-03, RF-04)."""

from pydantic import BaseModel, ConfigDict

from availability_hotel.models import SearchOutcome


class _View(BaseModel):
    model_config = ConfigDict(frozen=True)


class OfferView(_View):
    hotel: str
    room: str
    price: str
    currency: str
    provider: str


class FailedProviderView(_View):
    provider: str
    reason: str


class SearchResponse(_View):
    results: list[OfferView]
    failed_providers: list[FailedProviderView]


def render_search(outcome: SearchOutcome) -> SearchResponse:
    """Los montos salen como texto con 2 decimales, nunca como float (RF-06)."""
    return SearchResponse(
        results=[
            OfferView(
                hotel=rate.hotel,
                room=rate.room,
                price=f"{rate.price:.2f}",
                currency=rate.currency,
                provider=rate.provider,
            )
            for rate in outcome.results
        ],
        failed_providers=[
            FailedProviderView(provider=failed.provider, reason=failed.reason.value)
            for failed in outcome.failed_providers
        ],
    )
