"""Levanta los tres mocks en un solo proceso: `uv run python -m mocks`.

Puertos por defecto: provider_a 9001, provider_b 9002, provider_c 9003.
"""

import asyncio
import os

import uvicorn

from mocks.server import create_app

PORTS = {"provider_a": 9001, "provider_b": 9002, "provider_c": 9003}


async def main() -> None:
    host = os.environ.get("MOCK_HOST", "127.0.0.1")
    servers = [
        uvicorn.Server(
            uvicorn.Config(create_app(name), host=host, port=port, log_level="warning")
        )
        for name, port in PORTS.items()
    ]
    await asyncio.gather(*(server.serve() for server in servers))


if __name__ == "__main__":
    asyncio.run(main())
