"""API HTTP de punta a punta contra los mocks JSON con latencia real (HU008)."""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from availability_hotel.main import create_app
from tests.conftest import FakeSecretsClient, future
from tests.integration.conftest import local_settings

BODY = {
    "destino": "BOG",
    "check_in": future(10).isoformat(),
    "check_out": future(12).isoformat(),
    "huespedes": 2,
}


def _post(client, body=None):
    started = time.monotonic()
    response = client.post("/v1/availability", json=body or BODY)
    return response, time.monotonic() - started


def _failed(response):
    return {(f["provider"], f["reason"]) for f in response.json()["failed_providers"]}


def test_health_ready(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


@pytest.mark.slow
def test_default_mocks_b_excluded_by_timeout(client, mocks, caplog):
    caplog.set_level(logging.INFO)
    response, elapsed = _post(client)
    assert response.status_code == 200
    body = response.json()
    assert elapsed <= 2.2
    assert set(body) == {"results", "failed_providers"}
    for offer in body["results"]:
        assert set(offer) == {"hotel", "room", "price", "currency", "provider"}
    assert {o["provider"] for o in body["results"]} == {"provider_a", "provider_c"}
    assert _failed(response) == {("provider_b", "timeout")}
    central = next(o for o in body["results"] if o["hotel"] == "Hotel Central")
    assert central == {
        "hotel": "Hotel Central",
        "room": "Doble estandar",
        "price": "119.00",
        "currency": "USD",
        "provider": "provider_a",
    }
    prices = [Decimal(o["price"]) for o in body["results"]]
    assert prices == sorted(prices)
    events = [r for r in caplog.records if r.getMessage() == "provider_call"]
    assert {e.fields["provider_id"] for e in events} == set(mocks)
    b_call = next(e for e in events if e.fields["provider_id"] == "provider_b")
    assert b_call.fields["status"] == "timeout"
    assert "a-secret-key-123" not in caplog.text
    assert "b-pass-456" not in caplog.text


@pytest.mark.slow
def test_parallel_latencies_total_close_to_max_not_sum(client, mocks):
    mocks.configure(
        provider_a=("ok", 1500), provider_b=("ok", 1500), provider_c=("ok", 1500)
    )
    response, elapsed = _post(client)
    assert response.status_code == 200
    assert 1.45 <= elapsed < 2.0, elapsed
    assert response.json()["failed_providers"] == []
    providers = {o["provider"] for o in response.json()["results"]}
    assert providers == {"provider_a", "provider_b", "provider_c"}


@pytest.mark.slow
def test_b_on_time_includes_taxes(client, mocks):
    mocks.configure(provider_b="ok")
    response, elapsed = _post(client)
    assert response.status_code == 200 and elapsed < 2.0
    suite = next(
        o
        for o in response.json()["results"]
        if o["provider"] == "provider_b"
        and o["room"] == "Suite Junior"
        and o["price"] == "1469.06"
    )
    assert suite["currency"] == "COP"
    assert response.json()["failed_providers"] == []


def test_business_error_and_429(client, mocks):
    mocks.configure(
        provider_a="rate_limited", provider_b="empty", provider_c="invalid_dates"
    )
    response, _ = _post(client)
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert _failed(response) == {
        ("provider_a", "rate_limited"),
        ("provider_c", "business_error"),
    }
    again, _ = _post(client)
    assert ("provider_a", "rate_limited") in _failed(again)
    assert len(mocks["provider_a"].requests) == 1


def test_no_availability_is_not_failure(client, mocks):
    mocks.configure(provider_b="empty", provider_c="no_availability")
    response, _ = _post(client)
    assert response.status_code == 200
    assert _failed(response) == set()
    assert {o["provider"] for o in response.json()["results"]} == {"provider_a"}


def test_idempotency_keys_unique_and_auth_sent(client, mocks):
    mocks.configure(provider_b="empty")
    _post(client)
    _post(client)
    requests = mocks["provider_a"].requests
    keys = [r["idempotency-key"] for r in requests]
    assert len(keys) == 2 and len(set(keys)) == 2
    assert all(uuid.UUID(key).version == 4 for key in keys)
    assert all(r["authenticated"] for mock in mocks.values() for r in mock.requests)
    assert all(r["x-correlation-id"] for r in requests)


@pytest.mark.slow
def test_local_quota_protects_provider_a(client, mocks, caplog):
    caplog.set_level(logging.INFO)
    mocks.configure(provider_a=("ok", 50), provider_b="empty", provider_c="empty")
    with ThreadPoolExecutor(max_workers=15) as pool:
        responses = list(pool.map(lambda _: _post(client)[0], range(15)))
    assert all(r.status_code == 200 for r in responses)
    stamps = sorted(r["ts"] for r in mocks["provider_a"].requests)
    for start in stamps:
        assert sum(start <= t < start + 1.0 for t in stamps) <= 10
    reasons = [dict(_failed(r)).get("provider_a") for r in responses]
    assert "rate_limited" not in [
        e.fields.get("error_code")
        for e in caplog.records
        if e.getMessage() == "provider_call" and e.fields.get("http_status") == 429
    ]
    assert all(reason in (None, "rate_limited") for reason in reasons)
    completed = [r for r in caplog.records if r.getMessage() == "search_completed"]
    assert sum(r.fields["billable_requests"] for r in completed) == len(stamps)


def test_extra_fields_rejected_without_calling_providers(client, mocks):
    for extra in ({"hotel_ids": ["X"]}, {"rooms": 1}, {"currency": "USD"}):
        response = client.post("/v1/availability", json={**BODY, **extra})
        assert response.status_code == 422
    assert all(not mock.requests for mock in mocks.values())


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"check_out": future(5).isoformat()}, "check_out"),
        ({"huespedes": 0}, "huespedes"),
        ({"destino": ""}, "destino"),
        ({"check_in": "2026-13-45"}, "check_in"),
    ],
)
def test_invalid_query_422(client, mocks, overrides, field):
    response = client.post("/v1/availability", json={**BODY, **overrides})
    assert response.status_code == 422
    assert field in {error["loc"][-1] for error in response.json()["detail"]}
    assert all(not mock.requests for mock in mocks.values())


def test_malformed_json_422(client):
    response = client.post(
        "/v1/availability",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


def test_unknown_route_and_method(client):
    assert client.get("/nope").status_code == 404
    assert client.get("/v1/availability").status_code == 405


def _app_with(tmp_path, secrets, toml_override=None):
    config = str(tmp_path / "providers.toml") if toml_override else None
    if toml_override:
        (tmp_path / "providers.toml").write_text(toml_override)
    return create_app(
        settings_loader=lambda: local_settings(config) if config else local_settings(),
        secrets_factory=lambda settings: secrets,
        configure_logs=False,
    )


def test_readiness_503_when_secret_missing(tmp_path, provider_env):
    app = _app_with(tmp_path, FakeSecretsClient({}))
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 503
        assert "provider/a" in health.json()["error"]
        assert client.post("/v1/availability", json=BODY).status_code == 503


def test_readiness_503_when_timeout_invalid(tmp_path, provider_env):
    from tests.conftest import CONFIG_FILE

    text = CONFIG_FILE.read_text().replace("timeout_s = 2.0", "timeout_s = 5", 2)
    app = _app_with(tmp_path, FakeSecretsClient(), text)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 503
        assert "el maximo es 2.0" in health.json()["error"]


def test_settings_error_aborts_startup():
    from availability_hotel.config import Settings, SettingsError

    app = create_app(
        settings_loader=lambda: Settings.from_env({}), configure_logs=False
    )
    with pytest.raises(SettingsError):
        with TestClient(app):
            pass


def test_all_providers_disabled(tmp_path, provider_env):
    from tests.conftest import CONFIG_FILE

    text = CONFIG_FILE.read_text().replace("enabled = true", "enabled = false")

    class NoSecrets:
        def get_secret(self, secret_id):  # pragma: no cover
            raise AssertionError("no debe consultarse Secrets Manager")

    app = _app_with(tmp_path, NoSecrets(), text)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/v1/availability", json=BODY)
        assert response.json() == {"results": [], "failed_providers": []}


def test_unexpected_error_returns_500(client, monkeypatch):
    service = client.app.state.runtime.service

    async def boom(**kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(service, "search", boom)
    lenient = TestClient(client.app, raise_server_exceptions=False)
    response = lenient.post("/v1/availability", json=BODY)
    assert response.status_code == 500
    assert response.json() == {"detail": "error interno"}


def test_server_safety_timeout_returns_504(client, monkeypatch):
    import asyncio

    from availability_hotel.controllers import api

    async def hang(**kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(api, "REQUEST_TIMEOUT_S", 0.05)
    monkeypatch.setattr(client.app.state.runtime.service, "search", hang)
    assert client.post("/v1/availability", json=BODY).status_code == 504


def test_domain_validation_error_handler(client, monkeypatch):
    from availability_hotel.models import SearchQuery

    async def invalid(**kwargs):
        SearchQuery(destino="", check_in=future(1), check_out=future(2), huespedes=1)

    monkeypatch.setattr(client.app.state.runtime.service, "search", invalid)
    response = client.post("/v1/availability", json=BODY)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["destino"]
