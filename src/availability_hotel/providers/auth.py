"""Estrategias de autenticacion seleccionadas por configuracion (HU002 RF-03)."""

import base64
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from availability_hotel.config.schema import AuthConfig, AuthType


class AuthStrategy(Protocol):
    def headers(self) -> dict[str, str]: ...


class NoAuth:
    def headers(self) -> dict[str, str]:
        return {}

    def __repr__(self) -> str:
        return "NoAuth()"


class ApiKeyAuth:
    def __init__(self, header: str, secret: str) -> None:
        self._header = header
        self._secret = secret

    def headers(self) -> dict[str, str]:
        return {self._header: self._secret}

    def __repr__(self) -> str:
        return f"ApiKeyAuth(header={self._header!r}, secret='***')"


class BasicAuth:
    def __init__(self, user: str, password: str) -> None:
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        self._value = f"Basic {token}"

    def headers(self) -> dict[str, str]:
        return {"Authorization": self._value}

    def __repr__(self) -> str:
        return "BasicAuth(user='***', password='***')"


_FACTORIES: Mapping[AuthType, Callable[[AuthConfig, Mapping[str, Any]], Any]] = {
    AuthType.NONE: lambda config, secret: NoAuth(),
    AuthType.API_KEY: lambda config, secret: ApiKeyAuth(
        config.header or "", secret["api_key"]
    ),
    AuthType.BASIC: lambda config, secret: BasicAuth(
        secret["username"], secret["password"]
    ),
}


def build_auth(config: AuthConfig, secret: Mapping[str, Any] | None) -> AuthStrategy:
    return _FACTORIES[config.type](config, secret or {})
