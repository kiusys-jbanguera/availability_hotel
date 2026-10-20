# syntax=docker/dockerfile:1.7
# Imagen base fijada por etiqueta y digest (HU-S02 RF-01, P-01).
ARG PYTHON_IMAGE=python:3.15.0-slim-bookworm@sha256:2a41267d9de9d358f77a1de356e0f16ecba8d39827855be0ce9ef4792edce402
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.3@sha256:bee0a2a458fd956c5df7b8b4c5fed2257b0af34866e3da7b51db0be3acb375d1

FROM ${UV_IMAGE} AS uv

# --- builder: resuelve dependencias exactamente como en uv.lock -------------
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Capas ordenadas para cache: primero metadatos y lock, despues el codigo.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- dev: dependencias de desarrollo y pruebas -------------------------------
FROM builder AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen
COPY config ./config
COPY mocks ./mocks
COPY tests ./tests
ENV PATH=/app/.venv/bin:$PATH
CMD ["pytest", "--cov", "--cov-fail-under=90"]

# --- runtime: solo el entorno virtual y el codigo, sin uv ni compiladores ----
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PORT=8000
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app config ./config
COPY --chown=app:app docker/entrypoint.sh /usr/local/bin/entrypoint.sh
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8000')}/health\", timeout=2)"]
ENTRYPOINT ["entrypoint.sh"]

# --- mock: runtime + servidor de mocks JSON (solo entorno local) -------------
FROM runtime AS mock
COPY --chown=app:app mocks ./mocks
ENV MOCK_PORT=9000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('MOCK_PORT', '9000')}/_mock/health\", timeout=2)"]
CMD ["sh", "-c", "exec uvicorn mocks.server:app --host 0.0.0.0 --port ${MOCK_PORT}"]

# La imagen por defecto (`docker build .`) es la de runtime.
FROM runtime
