from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from availability_hotel.models import (
    MAX_GUESTS,
    MAX_NIGHTS,
    ProviderResult,
    ProviderStatus,
    Rate,
    SearchOutcome,
    SearchQuery,
)
from availability_hotel.views import render_search
from tests.conftest import future


def _errors(**fields):
    base = {"destino": "BOG", "check_in": future(1), "check_out": future(3)}
    base.update(huespedes=2)
    base.update(fields)
    with pytest.raises(ValidationError) as exc:
        SearchQuery(**base)
    return {error["loc"][0] for error in exc.value.errors()}


def test_valid_query_strips_destination():
    query = SearchQuery(
        destino="  BOG ", check_in=future(1), check_out=future(4), huespedes=1
    )
    assert query.destino == "BOG"
    assert query.nights == 3


def test_check_out_before_check_in_reports_check_out():
    assert _errors(check_in=future(5), check_out=future(3)) == {"check_out"}


def test_check_in_in_the_past():
    assert _errors(check_in=date.today() - timedelta(days=1)) == {"check_in"}


@pytest.mark.parametrize(
    "fields",
    [
        {"destino": "   "},
        {"huespedes": 0},
        {"huespedes": MAX_GUESTS + 1},
        {"huespedes": True},
        {"check_out": future(1 + MAX_NIGHTS + 1)},
        {"currency": "USD"},
    ],
)
def test_invalid_queries(fields):
    assert _errors(**fields)


def test_query_is_immutable():
    query = SearchQuery(
        destino="BOG", check_in=future(1), check_out=future(2), huespedes=1
    )
    with pytest.raises(ValidationError):
        query.destino = "MDE"


def _rate(**overrides):
    values = dict(
        hotel="H", room="R", price=Decimal("10.00"), currency="USD", provider="p"
    )
    values.update(overrides)
    return Rate(**values)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({}, None),
        ({"hotel": " "}, "missing_hotel"),
        ({"room": None}, "missing_room"),
        ({"price": None}, "invalid_price"),
        ({"price": Decimal("NaN")}, "invalid_price"),
        ({"price": Decimal("0")}, "non_positive_price"),
        ({"price": Decimal("-1")}, "non_positive_price"),
        ({"currency": "usd1"}, "invalid_currency"),
    ],
)
def test_rate_invalid_reason(overrides, reason):
    assert _rate(**overrides).invalid_reason() == reason


def test_outcome_sorted_by_price_and_failed_only():
    results = [
        ProviderResult(
            "provider_a",
            ProviderStatus.OK,
            (_rate(price=Decimal("119.00"), provider="provider_a"),),
        ),
        ProviderResult("provider_b", ProviderStatus.TIMEOUT),
        ProviderResult(
            "provider_c",
            ProviderStatus.OK,
            (_rate(price=Decimal("98.40"), provider="provider_c"),),
        ),
        ProviderResult("provider_d", ProviderStatus.OK),
        ProviderResult("provider_e", ProviderStatus.BUSINESS_ERROR),
    ]
    outcome = SearchOutcome.from_results(results)
    assert [r.price for r in outcome.results] == [Decimal("98.40"), Decimal("119.00")]
    assert [(f.provider, f.reason) for f in outcome.failed_providers] == [
        ("provider_b", "timeout"),
        ("provider_e", "business_error"),
    ]


def test_view_has_only_public_fields_and_string_prices():
    outcome = SearchOutcome.from_results(
        [
            ProviderResult(
                "provider_a",
                ProviderStatus.OK,
                (
                    _rate(
                        hotel="Hotel Central",
                        room="Doble estandar",
                        price=Decimal("119"),
                        provider="provider_a",
                    ),
                ),
            ),
            ProviderResult("provider_b", ProviderStatus.TIMEOUT),
        ]
    )
    body = render_search(outcome).model_dump()
    assert body == {
        "results": [
            {
                "hotel": "Hotel Central",
                "room": "Doble estandar",
                "price": "119.00",
                "currency": "USD",
                "provider": "provider_a",
            }
        ],
        "failed_providers": [{"provider": "provider_b", "reason": "timeout"}],
    }


def test_empty_outcome_is_valid():
    assert render_search(SearchOutcome()).model_dump() == {
        "results": [],
        "failed_providers": [],
    }
