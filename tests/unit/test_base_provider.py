"""Contrato comun (HU002) con un proveedor ficticio de schema plano."""

import asyncio
import logging
import time
from decimal import Decimal

import niquests
import pytest

from availability_hotel.config.schema import ProviderConfig
from availability_hotel.core.rate_limit import RateLimiter, SlidingWindowLimiter
from availability_hotel.models import Discarded, ProviderStatus
from availability_hotel.providers.auth import (
    ApiKeyAuth,
    BasicAuth,
    NoAuth,
    build_auth,
)
from availability_hotel.providers.base import BaseProvider, ProviderRequest
from availability_hotel.providers.registry import ProviderRegistry, RegistryError
from tests.conftest import FakeResponse, FakeSession

test_registry = ProviderRegistry()


@test_registry.register("fake_flat")
class FakeFlatProvider(BaseProvider):
    """Proveedor nuevo: solo implementa los puntos de variacion."""

    def build_request(self, query):
        return ProviderRequest("GET", "/rates", params={"city": query.destino})

    def map_response(self, payload, query):
        for item in payload["rates"]:
            if item.get("broken"):
                yield Discarded("broken_node")
                continue
            yield self.make_rate(item["hotel"], item["room"], item["price"], "USD")


class ExplodingProvider(FakeFlatProvider):
    def map_response(self, payload, query):
        raise KeyError("unexpected")


class StrictHeaderProvider(FakeFlatProvider):
    required_headers = ("x-required",)


def _config(**overrides):
    values = {
        "id": "fake",
        "enabled": True,
        "adapter": "fake_flat",
        "base_url": "http://fake.local/",
        "auth": {"type": "api_key", "header": "x-api-key", "secret_id": "fake"},
        "billing": {"cost_per_request": "0.01"},
    }
    values.update(overrides)
    return ProviderConfig.model_validate(values)


def _provider(outcome, delay=0.0, cls=FakeFlatProvider, limiter=None, **config):
    session = FakeSession(lambda method, url, kwargs: (delay, outcome))
    provider = cls(
        config=_config(**config),
        auth=ApiKeyAuth("x-api-key", "top-secret"),
        session=session,
        rate_limiter=limiter or RateLimiter(),
    )
    return provider, session


OK = FakeResponse(
    200,
    {
        "rates": [
            {"hotel": "H1", "room": "R1", "price": "100.005"},
            {"hotel": "H2", "room": "R2", "price": "80"},
        ]
    },
)


def _deadline(seconds=2.0):
    return time.monotonic() + seconds


async def test_new_provider_gets_common_flow(query, caplog):
    caplog.set_level(logging.INFO)
    provider, session = _provider(OK)
    result = await provider.search(query, _deadline())
    assert result.status is ProviderStatus.OK
    assert [r.price for r in result.rates] == [Decimal("100.01"), Decimal("80.00")]
    assert result.billable and result.cost == Decimal("0.01")
    [call] = session.calls
    assert call["url"] == "http://fake.local/rates"
    assert call["headers"]["x-api-key"] == "top-secret"
    assert 0 < call["timeout"] <= 2.0
    [record] = [r for r in caplog.records if r.getMessage() == "provider_call"]
    assert record.fields["status"] == "ok" and record.fields["results_count"] == 2


async def test_unexpected_exception_in_map_response_is_parse_error(query, caplog):
    provider, _ = _provider(OK, cls=ExplodingProvider)
    result = await provider.search(query, _deadline())
    assert result.status is ProviderStatus.PARSE_ERROR
    assert result.error_code == "KeyError"
    [record] = [r for r in caplog.records if r.getMessage() == "provider_call"]
    assert record.levelno == logging.ERROR and record.exc_info


async def test_partial_payload_keeps_valid_offers(query):
    payload = {
        "rates": [
            {"hotel": "H1", "room": "R1", "price": "10"},
            {"broken": True},
            {"hotel": "", "room": "R", "price": "5"},
            {"hotel": "H", "room": "R", "price": "-1"},
            {"hotel": "H", "room": "R", "price": "1,5"},
        ]
    }
    provider, _ = _provider(FakeResponse(200, payload))
    result = await provider.search(query, _deadline())
    assert result.status is ProviderStatus.OK and len(result.rates) == 1


async def test_all_offers_invalid_is_parse_error(query):
    payload = {"rates": [{"hotel": "", "room": "R", "price": "0"}]}
    provider, _ = _provider(FakeResponse(200, payload))
    result = await provider.search(query, _deadline())
    assert result.status is ProviderStatus.PARSE_ERROR
    assert result.error_code == "ALL_OFFERS_INVALID"


async def test_empty_offers_is_ok(query):
    provider, _ = _provider(FakeResponse(200, {"rates": []}))
    result = await provider.search(query, _deadline())
    assert result.status is ProviderStatus.OK and result.rates == ()


@pytest.mark.parametrize(
    ("response", "status", "code"),
    [
        (FakeResponse(401, {}), ProviderStatus.HTTP_ERROR, "AUTH"),
        (FakeResponse(403, {}), ProviderStatus.HTTP_ERROR, "AUTH"),
        (FakeResponse(503, {}), ProviderStatus.HTTP_ERROR, "HTTP_503"),
        (FakeResponse(404, {}), ProviderStatus.HTTP_ERROR, "HTTP_404"),
        (FakeResponse(200, raw=b"<html>"), ProviderStatus.PARSE_ERROR, None),
        (FakeResponse(200, raw=b""), ProviderStatus.PARSE_ERROR, None),
        (
            niquests.exceptions.ConnectionError("refused"),
            ProviderStatus.HTTP_ERROR,
            "ConnectionError",
        ),
        (niquests.exceptions.ReadTimeout("slow"), ProviderStatus.TIMEOUT, None),
    ],
)
async def test_error_classification(query, response, status, code):
    provider, _ = _provider(response)
    result = await provider.search(query, _deadline())
    assert (result.status, result.error_code) == (status, code)
    assert result.billable


async def test_provider_timeout_is_billable_and_bounded(query):
    provider, _ = _provider(OK, delay=1.0, timeout_s=0.1)
    started = time.monotonic()
    result = await provider.search(query, _deadline())
    assert result.status is ProviderStatus.TIMEOUT
    assert time.monotonic() - started < 0.3
    assert result.billable


async def test_effective_timeout_is_remaining_budget(query):
    provider, session = _provider(OK, delay=1.0)
    result = await provider.search(query, _deadline(0.1))
    assert result.status is ProviderStatus.TIMEOUT
    assert session.calls[0]["timeout"] <= 0.1


async def test_expired_budget_sends_nothing(query):
    provider, session = _provider(OK)
    result = await provider.search(query, time.monotonic() - 1)
    assert result.status is ProviderStatus.TIMEOUT
    assert session.calls == [] and not result.billable


async def test_mapping_beyond_deadline_is_timeout(query):
    provider, session = _provider(OK)
    provider.clock = lambda: 5.0 if session.calls else 0.0
    provider.rate_limiter = RateLimiter(clock=lambda: 0.0)
    result = await provider.search(query, deadline=1.0)
    assert result.status is ProviderStatus.TIMEOUT


async def test_no_local_quota_means_no_request_and_no_cost(query):
    limiter = SlidingWindowLimiter(1, 10.0)
    provider, session = _provider(OK, limiter=limiter)
    first = await provider.search(query, _deadline())
    second = await provider.search(query, _deadline(0.2))
    assert first.status is ProviderStatus.OK
    assert second.status is ProviderStatus.RATE_LIMITED
    assert not second.billable and len(session.calls) == 1


async def test_429_blocks_limiter_with_retry_after(query):
    limiter = RateLimiter()
    response = FakeResponse(429, {}, headers={"Retry-After": "1"})
    provider, session = _provider(response, limiter=limiter)
    first = await provider.search(query, _deadline())
    second = await provider.search(query, _deadline())
    assert first.status is ProviderStatus.RATE_LIMITED and first.billable
    assert second.status is ProviderStatus.RATE_LIMITED and not second.billable
    assert len(session.calls) == 1 and limiter.is_blocked()


async def test_missing_required_header_is_never_sent(query):
    provider, session = _provider(OK, cls=StrictHeaderProvider)
    result = await provider.search(query, _deadline())
    assert result.status is ProviderStatus.HTTP_ERROR
    assert result.error_code == "RuntimeError"
    assert session.calls == []


async def test_cancellation_logs_timeout_and_propagates(query, caplog):
    provider, _ = _provider(OK, delay=5)
    task = asyncio.create_task(provider.search(query, _deadline()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    [record] = [r for r in caplog.records if r.getMessage() == "provider_call"]
    assert record.fields["status"] == "timeout" and record.fields["billable"]


async def test_debug_logs_truncated_body(query, caplog):
    caplog.set_level(logging.DEBUG)
    big = FakeResponse(200, {"rates": [], "pad": "x" * 5000})
    provider, _ = _provider(big)
    await provider.search(query, _deadline())
    [record] = [r for r in caplog.records if r.getMessage() == "provider_response"]
    assert record.fields["body"].endswith("<truncated>")


async def test_api_key_never_logged(query, caplog):
    caplog.set_level(logging.DEBUG)
    provider, _ = _provider(OK)
    await provider.search(query, _deadline())
    assert "top-secret" not in caplog.text
    assert all(
        "top-secret" not in str(getattr(r, "fields", "")) for r in caplog.records
    )


def test_registry_rejects_duplicates():
    with pytest.raises(RegistryError):
        test_registry.register("fake_flat")(FakeFlatProvider)
    assert list(test_registry) == ["fake_flat"] and len(test_registry) == 1


def test_auth_strategies_from_config():
    api = build_auth(_config().auth, {"api_key": "k"})
    assert api.headers() == {"x-api-key": "k"} and "k'" not in repr(api)
    basic = build_auth(
        _config(auth={"type": "basic", "secret_id": "b"}).auth,
        {"username": "user", "password": "s3cr3t"},
    )
    assert basic.headers() == {"Authorization": "Basic dXNlcjpzM2NyM3Q="}
    assert "s3cr3t" not in repr(basic) and "user'" not in repr(basic)
    none = build_auth(_config(auth={"type": "none"}).auth, None)
    assert none.headers() == {} and repr(none) == "NoAuth()"
    assert isinstance(api, ApiKeyAuth) and isinstance(basic, BasicAuth)
    assert isinstance(none, NoAuth)
