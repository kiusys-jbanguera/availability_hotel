"""Criterios de bloqueo de HU-S01: niquests, FastAPI, uvicorn y pydantic sobre
Python 3.15 (RF-09 a RF-11)."""

import sys
from importlib.metadata import version

import niquests

from availability_hotel.config import Settings
from availability_hotel.main import create_app
from tests.conftest import CONFIG_FILE, FakeSecretsClient
from tests.integration.conftest import ServerThread, free_port


def test_python_and_pinned_versions():
    assert sys.version_info[:2] == (3, 15)
    assert version("niquests") == "3.21.2"
    assert version("fastapi") == "0.153.0"
    assert version("uvicorn") == "0.54.0"
    assert version("pydantic") == "2.14.1"
    starlette = tuple(int(part) for part in version("starlette").split(".")[:2])
    assert starlette >= (1, 7)


async def test_niquests_async_session_against_real_uvicorn(provider_env, mocks):
    app = create_app(
        settings_loader=lambda: Settings.from_env(
            {
                "APP_ENV": "local",
                "AWS_ENDPOINT_URL": "http://localstack.invalid:4566",
                "PROVIDERS_CONFIG": str(CONFIG_FILE),
            }
        ),
        secrets_factory=lambda settings: FakeSecretsClient(),
        configure_logs=False,
    )
    with ServerThread(app, free_port()) as server:
        async with niquests.AsyncSession() as session:
            health = await session.get(f"{server.url}/health", timeout=5)
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}
            mocks.configure(provider_b="empty")
            response = await session.post(
                f"{server.url}/v1/availability",
                json={
                    "destino": "BOG",
                    "check_in": "2099-01-10",
                    "check_out": "2099-01-12",
                    "huespedes": 2,
                },
                timeout=5,
            )
            assert response.status_code == 200
            assert response.json()["failed_providers"] == []
