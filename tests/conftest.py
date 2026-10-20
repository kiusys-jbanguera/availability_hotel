"""Utilidades compartidas por las pruebas."""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from availability_hotel.config.loader import LoadedConfig
from availability_hotel.config.schema import AppConfig, ProviderConfig
from availability_hotel.config.secrets import SecretError
from availability_hotel.models import SearchQuery
from availability_hotel.providers import build_providers, registry
from mocks.server import render

ROOT = Path(__file__).resolve().parents[1]
MOCK_DATA = ROOT / "mocks" / "data"
CONFIG_FILE = ROOT / "config" / "providers.toml"

SECRETS = {
    "provider/a": {"api_key": "a-secret-key-123"},
    "provider/b": {"username": "b-user", "password": "b-pass-456"},
    "provider/c": {"api_key": "c-secret-key-789"},
}


def future(days: int) -> date:
    return date.today() + timedelta(days=days)


@pytest.fixture
def query() -> SearchQuery:
    return SearchQuery(
        destino="BOG", check_in=future(10), check_out=future(12), huespedes=2
    )


class FakeSecretsClient:
    def __init__(self, secrets: dict[str, dict[str, Any]] | None = None) -> None:
        self.secrets = SECRETS if secrets is None else secrets
        self.calls: list[str] = []

    def get_secret(self, secret_id: str) -> MappingProxyType[str, Any]:
        self.calls.append(secret_id)
        if secret_id not in self.secrets:
            raise SecretError(secret_id, "no disponible (ResourceNotFoundException)")
        return MappingProxyType(self.secrets[secret_id])


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None

    @property
    def content(self) -> bytes:
        if self.raw is not None:
            return self.raw
        return json.dumps(self.payload).encode()


@dataclass
class FakeSession:
    """Sesion HTTP en memoria: responde con latencia simulada por proveedor."""

    responder: Callable[[str, str, dict[str, Any]], tuple[float, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append(
            {"method": method, "url": url, "ts": time.monotonic(), **kwargs}
        )
        delay, outcome = self.responder(method, url, kwargs)
        await asyncio.sleep(delay)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def scenario_response(
    provider: str, scenario: str, request: dict[str, Any]
) -> tuple[float, FakeResponse]:
    """Convierte un escenario JSON de `mocks/data` en una respuesta en memoria."""
    data = json.loads((MOCK_DATA / provider / f"{scenario}.json").read_text())
    latency = data.get("latency_ms", 0)
    if isinstance(latency, dict):
        latency = latency["max"]
    if "raw_body" in data:
        response = FakeResponse(data.get("status", 200), raw=data["raw_body"].encode())
    else:
        context = {"body": request.get("json"), "query": request.get("params") or {}}
        response = FakeResponse(
            data.get("status", 200),
            render(data.get("body", {}), context),
            headers=data.get("headers", {}),
        )
    return latency / 1000, response


def load_app_config(**search: Any) -> AppConfig:
    import tomllib

    raw = tomllib.loads(CONFIG_FILE.read_text())
    raw.setdefault("search", {}).update(search)
    from availability_hotel.config.loader import parse_config

    return parse_config(raw, registry, env={})


def provider_config(provider_id: str, **overrides: Any) -> ProviderConfig:
    base = next(p for p in load_app_config().providers if p.id == provider_id)
    return base.model_copy(update=overrides)


def build_from_scenarios(
    scenarios: dict[str, str], latency_scale: float = 1.0, **search: Any
) -> tuple[tuple[Any, ...], FakeSession]:
    """Proveedores reales A/B/C con sesion en memoria alimentada por los mocks."""
    app = load_app_config(**search)

    def responder(method: str, url: str, kwargs: dict[str, Any]) -> tuple[float, Any]:
        provider = next(p.id for p in app.providers if url.startswith(p.base_url))
        outcome = scenarios[provider]
        if isinstance(outcome, BaseException):
            return 0.01, outcome
        delay, response = scenario_response(provider, outcome, kwargs)
        return delay * latency_scale, response

    session = FakeSession(responder)
    secrets = {p.id: SECRETS[p.auth.secret_id] for p in app.providers}
    loaded = LoadedConfig(app=app, secrets=MappingProxyType(secrets))
    return build_providers(loaded, session), session
