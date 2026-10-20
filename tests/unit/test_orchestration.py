"""Orquestacion paralela y servicio de consulta (HU003, HU008, HU-S04)."""

import asyncio
import logging
import random
import time
from decimal import Decimal

import niquests
import pytest

from availability_hotel.config.schema import ProviderConfig
from availability_hotel.controllers import Orchestrator, SearchService
from availability_hotel.core.rate_limit import RateLimiter
from availability_hotel.models import ProviderStatus
from availability_hotel.providers.auth import NoAuth
from tests.conftest import FakeResponse, FakeSession, build_from_scenarios, future
from tests.unit.test_base_provider import FakeFlatProvider


def _service(providers, timeout_s=2.0, max_concurrency=1000):
    return SearchService(Orchestrator(providers, timeout_s, max_concurrency))


async def _run(service, **overrides):
    params = dict(destino="BOG", check_in=future(10), check_out=future(12), huespedes=2)
    params.update(overrides)
    started = time.monotonic()
    response = await service.search(**params)
    return response, time.monotonic() - started


def _completed(caplog):
    [record] = [r for r in caplog.records if r.getMessage() == "search_completed"]
    return record.fields


@pytest.mark.slow
async def test_partial_response_with_slow_provider(caplog):
    caplog.set_level(logging.INFO)
    providers, _ = build_from_scenarios(
        {"provider_a": "ok", "provider_b": "slow", "provider_c": "ok"}
    )
    response, elapsed = await _run(_service(providers))
    assert elapsed <= 2.1
    assert {r.provider for r in response.results} == {"provider_a", "provider_c"}
    assert [f.model_dump() for f in response.failed_providers] == [
        {"provider": "provider_b", "reason": "timeout"}
    ]
    prices = [Decimal(r.price) for r in response.results]
    assert prices == sorted(prices)
    summary = _completed(caplog)
    assert summary["providers_queried"] == 3
    assert summary["responded_in_time"] == 2
    assert summary["excluded_by_timeout"] == 1
    assert summary["timeout_providers"] == ["provider_b"]
    assert summary["billable_requests"] == 1
    assert summary["estimated_cost"] == Decimal("0.0050")


@pytest.mark.slow
async def test_real_parallelism():
    providers, _ = build_from_scenarios(
        {"provider_a": "slow", "provider_b": "slow", "provider_c": "slow"},
        latency_scale=0.5,
    )
    response, elapsed = await _run(_service(providers))
    # A y C tardan 0.75 s y B 1.5 s: paralelo ~1.5 s, secuencial seria 3 s.
    assert 1.4 <= elapsed < 1.9
    assert response.failed_providers == []


async def test_failures_are_isolated():
    providers, _ = build_from_scenarios(
        {
            "provider_a": "ok",
            "provider_b": "ok",
            "provider_c": niquests.exceptions.ConnectionError("refused"),
        },
        latency_scale=0.1,
    )
    response, _ = await _run(_service(providers))
    assert {r.provider for r in response.results} == {"provider_a", "provider_b"}
    assert [f.model_dump() for f in response.failed_providers] == [
        {"provider": "provider_c", "reason": "http_error"}
    ]


async def test_a_ok_b_timeout_c_business_error():
    providers, _ = build_from_scenarios(
        {"provider_a": "ok", "provider_b": "slow", "provider_c": "invalid_dates"},
        latency_scale=0.1,
        timeout_s=0.2,
    )
    response, _ = await _run(_service(providers, timeout_s=0.2))
    assert {r.provider for r in response.results} == {"provider_a"}
    assert {(f.provider, f.reason) for f in response.failed_providers} == {
        ("provider_b", "timeout"),
        ("provider_c", "business_error"),
    }


async def test_no_provider_answers_in_time():
    providers, _ = build_from_scenarios(
        {"provider_a": "timeout", "provider_b": "spike", "provider_c": "slow"},
        latency_scale=0.1,
    )
    response, elapsed = await _run(_service(providers, timeout_s=0.1))
    assert response.results == []
    assert {f.reason for f in response.failed_providers} == {"timeout"}
    assert len(response.failed_providers) == 3
    assert elapsed < 0.3


async def test_zero_providers(caplog):
    response, elapsed = await _run(_service([]))
    assert response.results == [] and response.failed_providers == []
    assert elapsed < 0.05
    assert any(r.getMessage() == "no_enabled_providers" for r in caplog.records)


async def test_invalid_query_calls_no_provider():
    providers, session = build_from_scenarios(
        {"provider_a": "ok", "provider_b": "ok", "provider_c": "ok"}
    )
    with pytest.raises(Exception) as exc:
        await _run(_service(providers), check_out=future(5))
    assert "check_out" in str(exc.value)
    assert session.calls == []


async def test_correlation_id_shared_by_all_events(caplog):
    caplog.set_level(logging.INFO)
    providers, session = build_from_scenarios(
        {"provider_a": "ok", "provider_b": "ok", "provider_c": "ok"},
        latency_scale=0.05,
    )
    from availability_hotel.core.logging import ContextFilter

    caplog.handler.addFilter(ContextFilter())
    await _run(_service(providers))
    events = [r for r in caplog.records if r.getMessage() != "offer_discarded"]
    ids = {r.correlation_id for r in events}
    assert len(ids) == 1 and None not in ids
    calls = [r for r in events if r.getMessage() == "provider_call"]
    assert len(calls) == 3
    assert {c["headers"]["X-Correlation-ID"] for c in session.calls} == ids


async def test_orchestrator_cancels_stuck_tasks_without_orphans():
    class StuckProvider(FakeFlatProvider):
        async def search(self, query, deadline):
            await asyncio.sleep(10)

    config = ProviderConfig.model_validate(
        {
            "id": "stuck",
            "enabled": True,
            "adapter": "x",
            "base_url": "http://x",
            "auth": {"type": "none"},
        }
    )
    stuck = StuckProvider(config, NoAuth(), None, RateLimiter())
    response, elapsed = await _run(_service([stuck], timeout_s=0.1))
    assert [f.model_dump() for f in response.failed_providers] == [
        {"provider": "stuck", "reason": "timeout"}
    ]
    assert elapsed < 0.3
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert pending == []


@pytest.mark.slow
async def test_thousand_simulated_providers():
    rng = random.Random(42)
    delays = {f"p{i}": rng.uniform(0.1, 3.0) for i in range(1000)}

    def responder(method, url, kwargs):
        provider_id = url.split("//")[1].split(".")[0]
        payload = {"rates": [{"hotel": "H", "room": "R", "price": "10"}]}
        return delays[provider_id], FakeResponse(200, payload)

    session = FakeSession(responder)
    providers = [
        FakeFlatProvider(
            ProviderConfig.model_validate(
                {
                    "id": pid,
                    "enabled": True,
                    "adapter": "fake_flat",
                    "base_url": f"http://{pid}.local",
                    "auth": {"type": "none"},
                }
            ),
            NoAuth(),
            session,
            RateLimiter(),
        )
        for pid in delays
    ]
    response, elapsed = await _run(_service(providers))
    surely_on_time = sum(delay < 1.8 for delay in delays.values())
    within_budget = sum(delay < 2.0 for delay in delays.values())
    assert elapsed <= 2.2
    assert surely_on_time <= len(response.results) <= within_budget
    assert len(response.results) + len(response.failed_providers) == 1000
    assert {f.reason for f in response.failed_providers} == {ProviderStatus.TIMEOUT}


async def test_concurrency_limit_is_respected():
    active = peak = 0

    class CountingProvider(FakeFlatProvider):
        async def search(self, query, deadline):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return await super().search(query, deadline)

    session = FakeSession(lambda m, u, k: (0, FakeResponse(200, {"rates": []})))
    providers = [
        CountingProvider(
            ProviderConfig.model_validate(
                {
                    "id": f"p{i}",
                    "enabled": True,
                    "adapter": "fake_flat",
                    "base_url": "http://p.local",
                    "auth": {"type": "none"},
                }
            ),
            NoAuth(),
            session,
            RateLimiter(),
        )
        for i in range(50)
    ]
    await _run(_service(providers, max_concurrency=5))
    assert peak == 5
