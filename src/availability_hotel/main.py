"""Aplicacion FastAPI: `uvicorn availability_hotel.main:app` (HU008, HU-S02)."""

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from availability_hotel import __version__
from availability_hotel.config import Settings, SettingsError, build_secrets_client
from availability_hotel.controllers.api import router
from availability_hotel.controllers.runtime import (
    SecretsFactory,
    SessionFactory,
    build_runtime,
    default_session_factory,
)
from availability_hotel.core.logging import (
    configure_logging,
    get_logger,
    log_event,
    shutdown_logging,
)

logger = get_logger("availability_hotel.app")


def create_app(
    settings_loader: Callable[[], Settings] = Settings.from_env,
    secrets_factory: SecretsFactory = build_secrets_client,
    session_factory: SessionFactory = default_session_factory,
    configure_logs: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if configure_logs:
            configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
        try:
            settings = settings_loader()
        except SettingsError as exc:
            # Error de entorno: aborta el arranque con codigo distinto de 0.
            log_event(logger, "settings_error", logging.CRITICAL, error=str(exc))
            raise
        if configure_logs:
            configure_logging(settings.log_level)
        app.state.runtime = await build_runtime(
            settings, secrets_factory, session_factory
        )
        try:
            yield
        finally:
            await app.state.runtime.aclose()
            if configure_logs:
                shutdown_logging()

    docs_enabled = os.environ.get("APP_ENV") != "prod"
    app = FastAPI(
        title="availability_hotel",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.include_router(router)

    @app.exception_handler(ValidationError)
    async def _domain_validation(request: Request, exc: ValidationError):
        errors = exc.errors(include_url=False, include_context=False)
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log_event(logger, "unhandled_error", logging.ERROR, exc_info=True)
        return JSONResponse({"detail": "error interno"}, status_code=500)

    return app


app = create_app()
