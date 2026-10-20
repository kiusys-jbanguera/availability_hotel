"""Mocks HTTP reales (uvicorn en hilos) y la aplicacion FastAPI conectada a
ellos con secretos en memoria."""

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from availability_hotel.config import Settings
from availability_hotel.main import create_app
from mocks.server import MockProvider, create_app as create_mock_app
from tests.conftest import CONFIG_FILE, FakeSecretsClient

PROVIDERS = ("provider_a", "provider_b", "provider_c")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ServerThread:
    def __init__(self, app: Any, port: int) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self) -> "ServerThread":
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:  # pragma: no cover
                raise RuntimeError("el servidor no arranco")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


class Mocks(dict[str, MockProvider]):
    def configure(self, **scenarios: str | tuple[str, float]) -> None:
        for name, spec in scenarios.items():
            scenario, latency = spec if isinstance(spec, tuple) else (spec, None)
            self[name].scenario = scenario
            self[name].latency_override_ms = latency

    def reset(self) -> None:
        for mock in self.values():
            mock.scenario = mock.manifest["default_scenario"]
            mock.latency_override_ms = None
            mock.requests.clear()
            if mock._window is not None:
                mock._window.clear()


@pytest.fixture(scope="session")
def mock_servers() -> Iterator[tuple[Mocks, dict[str, str]]]:
    mocks = Mocks()
    urls: dict[str, str] = {}
    servers = []
    for name in PROVIDERS:
        app = create_mock_app(name)
        mocks[name] = app.state.mock
        server = ServerThread(app, free_port()).__enter__()
        servers.append(server)
        urls[name] = server.url
    yield mocks, urls
    for server in servers:
        server.__exit__()


@pytest.fixture
def mocks(mock_servers) -> Iterator[Mocks]:
    mocks, _ = mock_servers
    mocks.reset()
    yield mocks
    mocks.reset()


@pytest.fixture
def provider_env(mock_servers, monkeypatch) -> dict[str, str]:
    _, urls = mock_servers
    env = {f"{name.upper()}_BASE_URL": url for name, url in urls.items()}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def local_settings(config: str = str(CONFIG_FILE)) -> Settings:
    return Settings.from_env(
        {
            "APP_ENV": "local",
            "AWS_ENDPOINT_URL": "http://localstack.invalid:4566",
            "PROVIDERS_CONFIG": config,
        }
    )


@pytest.fixture
def client(provider_env, mocks) -> Iterator[TestClient]:
    app = create_app(
        settings_loader=local_settings,
        secrets_factory=lambda settings: FakeSecretsClient(),
        configure_logs=False,
    )
    with TestClient(app) as test_client:
        yield test_client
