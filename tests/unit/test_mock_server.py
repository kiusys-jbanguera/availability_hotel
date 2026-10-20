"""Contrato de control de los mocks usado por la guia del README."""

import json

import pytest
from fastapi.testclient import TestClient

from mocks.server import DATA_DIR, create_app

AUTH_HEADERS = {
    "provider_a": {"x-api-key": "k", "idempotency-key": "i"},
    "provider_b": {"authorization": "Basic dTpw"},
    "provider_c": {"x-api-key": "k"},
}
SCENARIOS = [
    (provider.name, path.stem)
    for provider in sorted(DATA_DIR.iterdir())
    for path in sorted(provider.glob("*.json"))
    if not path.stem.startswith("_")
]


def _client(name: str) -> TestClient:
    return TestClient(create_app(name))


def _put(client: TestClient, **payload: object):
    return client.put("/_mock/scenario", json=payload)


def test_default_scenario_comes_from_manifest(monkeypatch):
    monkeypatch.delenv("MOCK_SCENARIO", raising=False)
    assert _client("provider_a").get("/_mock/health").json()["scenario"] == "ok"
    assert _client("provider_b").get("/_mock/health").json()["scenario"] == "slow"
    assert _client("provider_c").get("/_mock/health").json()["scenario"] == "ok"


def test_env_sets_initial_scenario_and_put_overrides_it(monkeypatch):
    monkeypatch.setenv("MOCK_SCENARIO", "ok")
    client = _client("provider_b")
    assert client.get("/_mock/scenarios").json()["active"] == "ok"
    assert _put(client, scenario="spike").json() == {
        "scenario": "spike",
        "latency_ms": None,
    }
    assert client.get("/_mock/health").json()["scenario"] == "spike"


def test_put_is_per_provider_and_rejects_unknown_scenarios(monkeypatch):
    monkeypatch.delenv("MOCK_SCENARIO", raising=False)
    provider_a, provider_c = _client("provider_a"), _client("provider_c")
    _put(provider_a, scenario="timeout")
    response = _put(provider_a, scenario="no_existe")
    assert response.status_code == 404
    assert provider_a.get("/_mock/health").json()["scenario"] == "timeout"
    assert provider_c.get("/_mock/health").json()["scenario"] == "ok"


def test_put_without_latency_resets_the_override(monkeypatch):
    monkeypatch.delenv("MOCK_SCENARIO", raising=False)
    client = _client("provider_a")
    assert _put(client, scenario="ok", latency_ms=2500).json()["latency_ms"] == 2500
    assert _put(client, scenario="ok").json()["latency_ms"] is None
    assert client.app.state.mock.latency_override_ms is None


@pytest.mark.parametrize(("provider", "scenario"), SCENARIOS)
def test_every_scenario_is_selectable_and_served(monkeypatch, provider, scenario):
    monkeypatch.delenv("MOCK_SCENARIO", raising=False)
    expected = json.loads((DATA_DIR / provider / f"{scenario}.json").read_text())
    client = _client(provider)
    assert scenario in client.get("/_mock/scenarios").json()["available"]
    assert _put(client, scenario=scenario, latency_ms=0).status_code == 200
    response = client.post("/any", json={}, headers=AUTH_HEADERS[provider])
    assert response.status_code == expected.get("status", 200)
