"""Servidor mock generico de proveedores, guiado por archivos JSON.

Cada proveedor tiene un directorio `mocks/data/<proveedor>/` con:
- `_provider.json`: autenticacion esperada, headers obligatorios, rate limit
  propio del proveedor y escenario por defecto.
- `<escenario>.json`: `latency_ms` (numero o `{"min", "max"}`), `status`,
  `headers` y `body` (payload nativo del proveedor) o `raw_body` (texto).

El body admite placeholders `{{body.ruta}}` / `{{query.param}}` que se
reemplazan con datos del request (por ejemplo, las fechas de la estadia).

Escenario activo: header `X-Mock-Scenario` (solo llamadas directas al mock) >
`PUT /_mock/scenario` > `MOCK_SCENARIO` (al arrancar) > `default_scenario`.
Latencia: `latency_ms` del `PUT` > `MOCK_LATENCY_MS` > la del escenario; un
`PUT` sin `latency_ms` quita la forzada por el `PUT` anterior.
"""

import asyncio
import json
import os
import random
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

DATA_DIR = Path(__file__).parent / "data"
_PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_RECORDED_HEADERS = ("idempotency-key", "x-correlation-id")


def _lookup(context: Any, path: str) -> Any:
    current = context
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def render(template: Any, context: dict[str, Any]) -> Any:
    if isinstance(template, str):
        whole = _PLACEHOLDER.fullmatch(template)
        if whole:
            return _lookup(context, whole.group(1))
        return _PLACEHOLDER.sub(
            lambda m: str(_lookup(context, m.group(1)) or ""), template
        )
    if isinstance(template, dict):
        return {key: render(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [render(item, context) for item in template]
    return template


def _latency_s(spec: Any) -> float:
    override = os.environ.get("MOCK_LATENCY_MS")
    if override:
        return float(override) / 1000
    if isinstance(spec, dict):
        return random.uniform(spec["min"], spec["max"]) / 1000
    return float(spec or 0) / 1000


class MockProvider:
    def __init__(self, name: str, data_dir: Path = DATA_DIR) -> None:
        self.name = name
        self.directory = data_dir / name
        self.manifest = self._read("_provider")
        self.scenario = os.environ.get("MOCK_SCENARIO") or self.manifest.get(
            "default_scenario", "ok"
        )
        self.latency_override_ms: float | None = None
        self.requests: list[dict[str, Any]] = []
        quota = self.manifest.get("rate_limit")
        self._window: deque[float] | None = deque() if quota else None

    def _read(self, scenario: str) -> dict[str, Any]:
        path = self.directory / f"{scenario}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def scenarios(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json") if p.stem[0] != "_")

    def _over_quota(self, now: float) -> bool:
        quota = self.manifest.get("rate_limit")
        if self._window is None or not quota:
            return False
        while self._window and self._window[0] <= now - quota["per_seconds"]:
            self._window.popleft()
        if len(self._window) >= quota["requests"]:
            return True
        self._window.append(now)
        return False

    def _guard(self, headers: dict[str, str], now: float) -> dict[str, Any] | None:
        auth = self.manifest.get("auth", {})
        header = (auth.get("header") or "authorization").lower()
        if auth.get("type", "none") != "none" and not headers.get(header):
            return {"status": 401, "body": {"error": "UNAUTHORIZED"}}
        if auth.get("type") == "basic" and not headers[header].startswith("Basic "):
            return {"status": 401, "body": {"error": "UNAUTHORIZED"}}
        for required in self.manifest.get("required_headers", []):
            if not headers.get(required):
                return {"status": 422, "body": {"error": "IDEMPOTENCY_KEY_REQUIRED"}}
        if self._over_quota(now):
            return {
                "status": 429,
                "headers": {"Retry-After": "1"},
                "body": {"error": "RATE_LIMIT_EXCEEDED"},
            }
        return None

    async def handle(self, request: Request) -> Response:
        now = time.monotonic()
        headers = {key.lower(): value for key, value in request.headers.items()}
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        self.requests.append(
            {
                "ts": time.time(),
                "method": request.method,
                "path": request.url.path,
                "authenticated": bool(
                    headers.get(
                        (
                            self.manifest.get("auth", {}).get("header")
                            or "authorization"
                        ).lower()
                    )
                ),
                **{name: headers.get(name) for name in _RECORDED_HEADERS},
            }
        )
        scenario = self._guard(headers, now) or self._read(
            headers.get("x-mock-scenario") or self.scenario
        )
        latency = (
            self.latency_override_ms / 1000
            if self.latency_override_ms is not None
            else _latency_s(scenario.get("latency_ms"))
        )
        await asyncio.sleep(latency)
        response_headers = scenario.get("headers", {})
        if "raw_body" in scenario:
            return Response(
                scenario["raw_body"],
                status_code=scenario.get("status", 200),
                headers=response_headers,
                media_type="text/plain",
            )
        context = {"body": body, "query": dict(request.query_params)}
        return JSONResponse(
            render(scenario.get("body", {}), context),
            status_code=scenario.get("status", 200),
            headers=response_headers,
        )


def create_app(name: str | None = None) -> FastAPI:
    provider = MockProvider(name or os.environ.get("MOCK_PROVIDER", "provider_a"))
    app = FastAPI(title=f"mock-{provider.name}", docs_url=None, redoc_url=None)
    app.state.mock = provider

    @app.get("/_mock/health")
    async def health() -> dict[str, Any]:
        return {"provider": provider.name, "scenario": provider.scenario}

    @app.get("/_mock/scenarios")
    async def scenarios() -> dict[str, Any]:
        return {"active": provider.scenario, "available": provider.scenarios()}

    @app.put("/_mock/scenario")
    async def set_scenario(payload: dict[str, Any]) -> dict[str, Any]:
        name = payload.get("scenario", provider.scenario)
        if name not in provider.scenarios():
            return JSONResponse({"error": f"escenario '{name}' inexistente"}, 404)
        provider.scenario = name
        provider.latency_override_ms = payload.get("latency_ms")
        return {
            "scenario": provider.scenario,
            "latency_ms": provider.latency_override_ms,
        }

    @app.get("/_mock/requests")
    async def requests() -> list[dict[str, Any]]:
        return provider.requests

    @app.delete("/_mock/requests")
    async def reset() -> dict[str, int]:
        cleared = len(provider.requests)
        provider.requests.clear()
        if provider._window is not None:
            provider._window.clear()
        return {"cleared": cleared}

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def serve(request: Request) -> Response:
        return await provider.handle(request)

    return app


app = create_app()
