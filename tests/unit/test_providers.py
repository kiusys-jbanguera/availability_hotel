"""Adaptadores A, B y C contra los escenarios JSON de `mocks/data` (HU005-HU007)."""

import logging
import time
import uuid
from decimal import Decimal

import pytest

from availability_hotel.models import ProviderStatus
from tests.conftest import build_from_scenarios


def _provider(provider_id, scenario):
    providers, session = build_from_scenarios(
        {"provider_a": scenario, "provider_b": scenario, "provider_c": scenario},
        latency_scale=0.0,
    )
    return next(p for p in providers if p.id == provider_id), session


async def _search(provider_id, scenario, query):
    provider, session = _provider(provider_id, scenario)
    return await provider.search(query, time.monotonic() + 2), session


# Proveedor A -------------------------------------------------------------------


async def test_a_standard_offer(query):
    result, session = await _search("provider_a", "ok", query)
    assert result.status is ProviderStatus.OK
    central = next(r for r in result.rates if r.hotel == "Hotel Central")
    assert (central.room, central.price, central.currency, central.provider) == (
        "Doble estandar",
        Decimal("119.00"),
        "USD",
        "provider_a",
    )
    coded = next(r for r in result.rates if r.hotel == "HC-004")
    assert coded.room == "TWN"
    [call] = session.calls
    assert call["method"] == "GET" and call["url"].endswith("/v1/availability")
    assert call["params"] == {
        "destination": "BOG",
        "checkin": query.check_in.isoformat(),
        "checkout": query.check_out.isoformat(),
        "adults": 2,
    }
    assert call["headers"]["x-api-key"] == "a-secret-key-123"


async def test_a_idempotency_key_unique_per_request(query):
    provider, session = _provider("provider_a", "ok")
    first = await provider.search(query, time.monotonic() + 2)
    second = await provider.search(query, time.monotonic() + 2)
    keys = [call["headers"]["idempotency-key"] for call in session.calls]
    assert keys[0] != keys[1]
    assert all(uuid.UUID(key).version == 4 for key in keys)
    assert [first.idempotency_key, second.idempotency_key] == keys


async def test_a_billable_and_cost(query):
    result, _ = await _search("provider_a", "ok", query)
    assert result.billable and result.cost == Decimal("0.0050")


@pytest.mark.parametrize(
    ("scenario", "status", "code"),
    [
        ("empty", ProviderStatus.OK, None),
        ("rate_limited", ProviderStatus.RATE_LIMITED, "RATE_LIMITED"),
        ("server_error", ProviderStatus.HTTP_ERROR, "HTTP_503"),
        ("auth_error", ProviderStatus.HTTP_ERROR, "AUTH"),
        ("idempotency_conflict", ProviderStatus.HTTP_ERROR, "IDEMPOTENCY"),
        ("invalid_json", ProviderStatus.PARSE_ERROR, None),
    ],
)
async def test_a_error_table(query, scenario, status, code):
    result, _ = await _search("provider_a", scenario, query)
    assert (result.status, result.error_code) == (status, code)
    assert result.billable


async def test_a_429_blocks_following_requests(query):
    provider, session = _provider("provider_a", "rate_limited")
    await provider.search(query, time.monotonic() + 2)
    second = await provider.search(query, time.monotonic() + 2)
    assert second.status is ProviderStatus.RATE_LIMITED and not second.billable
    assert len(session.calls) == 1


async def test_a_auth_error_logged_as_error(query, caplog):
    await _search("provider_a", "auth_error", query)
    [record] = [r for r in caplog.records if r.getMessage() == "provider_call"]
    assert record.levelno == logging.ERROR


# Proveedor B -------------------------------------------------------------------


async def test_b_nested_schema_taxes_and_discards(query, caplog):
    caplog.set_level(logging.DEBUG)
    result, session = await _search("provider_b", "ok", query)
    assert result.status is ProviderStatus.OK
    prices = {(r.hotel, r.room, r.price) for r in result.rates}
    assert ("Hotel Andino Plaza", "Suite Junior", Decimal("1469.06")) in prices
    assert ("Hotel Andino Plaza", "Doble superior", Decimal("1166.20")) in prices
    assert ("Hotel Chico Norte", "Estandar", Decimal("542.52")) in prices
    assert len(result.rates) == 4
    assert {r.currency for r in result.rates} == {"COP"}
    reasons = sorted(
        r.fields["reason"]
        for r in caplog.records
        if r.getMessage() == "offer_discarded"
    )
    assert reasons == ["invalid_date", "missing_amount"]
    [call] = session.calls
    assert call["headers"]["Authorization"].startswith("Basic ")
    estancia = call["json"]["Consulta"]["Estancia"]
    assert estancia["Entrada"] == query.check_in.strftime("%d/%m/%Y")


def _b_payload(desde, hasta, valor="1.234,50"):
    return {
        "Respuesta": {
            "Hoteles": {
                "Hotel": {
                    "Nombre": "Hotel X",
                    "Habitaciones": {
                        "Habitacion": {
                            "Descripcion": "Doble",
                            "Tarifas": {
                                "Tarifa": {
                                    "Periodo": {"Desde": desde, "Hasta": hasta},
                                    "Importe": {"Valor": valor, "Divisa": "EUR"},
                                }
                            },
                        }
                    },
                }
            }
        }
    }


def test_b_yyyymmdd_format_and_single_nodes(query):
    provider, _ = _provider("provider_b", "ok")
    payload = _b_payload(
        query.check_in.strftime("%Y%m%d"), query.check_out.strftime("%Y%m%d")
    )
    [rate] = list(provider.map_response(payload, query))
    assert rate.price == Decimal("1469.06") and rate.currency == "EUR"


def test_b_stay_mismatch_is_discarded(query):
    provider, _ = _provider("provider_b", "ok")
    payload = _b_payload("01/01/2030", "02/01/2030")
    [item] = list(provider.map_response(payload, query))
    assert item.reason == "stay_mismatch"


def test_b_round_half_up(query):
    provider, _ = _provider("provider_b", "ok")
    rate = provider.make_rate("H", "R", "0,05", "COP")
    assert rate.price == Decimal("0.06")


@pytest.mark.parametrize(
    ("scenario", "status", "code"),
    [
        ("auth_error", ProviderStatus.HTTP_ERROR, "AUTH"),
        ("server_error", ProviderStatus.HTTP_ERROR, "HTTP_500"),
        ("empty", ProviderStatus.OK, None),
    ],
)
async def test_b_error_table(query, scenario, status, code):
    result, _ = await _search("provider_b", scenario, query)
    assert (result.status, result.error_code) == (status, code)
    assert not result.billable


async def test_b_slow_is_timeout(query):
    providers, _ = build_from_scenarios({"provider_b": "slow"}, latency_scale=0.1)
    provider_b = next(p for p in providers if p.id == "provider_b")
    result = await provider_b.search(query, time.monotonic() + 0.2)
    assert result.status is ProviderStatus.TIMEOUT


# Proveedor C -------------------------------------------------------------------


async def test_c_successful_response(query):
    result, session = await _search("provider_c", "ok", query)
    assert result.status is ProviderStatus.OK
    assert {(r.hotel, r.room, r.price) for r in result.rates} == {
        ("Hotel Bacata", "Estandar", Decimal("98.40")),
        ("Hotel Usaquen Boutique", "Deluxe king", Decimal("156.00")),
        ("C-79", "FAM", Decimal("201.75")),
    }
    [call] = session.calls
    assert call["json"]["city_code"] == "BOG"
    assert call["headers"]["x-api-key"] == "c-secret-key-789"


@pytest.mark.parametrize(
    ("scenario", "status", "code", "level"),
    [
        ("no_availability", ProviderStatus.OK, None, logging.INFO),
        ("empty", ProviderStatus.OK, None, logging.INFO),
        (
            "invalid_dates",
            ProviderStatus.BUSINESS_ERROR,
            "INVALID_DATES",
            logging.WARNING,
        ),
        (
            "invalid_destination",
            ProviderStatus.BUSINESS_ERROR,
            "INVALID_DESTINATION",
            logging.WARNING,
        ),
        ("invalid_key", ProviderStatus.BUSINESS_ERROR, "AUTH", logging.ERROR),
        (
            "internal_error",
            ProviderStatus.BUSINESS_ERROR,
            "INTERNAL_ERROR",
            logging.ERROR,
        ),
        (
            "unknown_code",
            ProviderStatus.BUSINESS_ERROR,
            "QUOTA_EXHAUSTED_XYZ",
            logging.WARNING,
        ),
        (
            "error_with_results",
            ProviderStatus.BUSINESS_ERROR,
            "INTERNAL_ERROR",
            logging.ERROR,
        ),
        (
            "errors_list",
            ProviderStatus.BUSINESS_ERROR,
            "INVALID_DESTINATION",
            logging.WARNING,
        ),
        ("http_500", ProviderStatus.HTTP_ERROR, "HTTP_500", logging.WARNING),
        ("empty_body", ProviderStatus.PARSE_ERROR, None, logging.WARNING),
    ],
)
async def test_c_business_error_catalog(query, caplog, scenario, status, code, level):
    result, _ = await _search("provider_c", scenario, query)
    assert (result.status, result.error_code) == (status, code)
    assert result.rates == ()
    [record] = [r for r in caplog.records if r.getMessage() == "provider_call"]
    assert record.levelno == level
    if code:
        assert record.fields["error_code"] == code


def test_c_status_missing_is_not_error(query):
    from availability_hotel.providers.business_errors import check_business_error

    provider, _ = _provider("provider_c", "ok")
    check_business_error(provider.config.business_errors, {"data": {"results": []}})
