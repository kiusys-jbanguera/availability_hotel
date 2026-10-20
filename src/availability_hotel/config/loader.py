"""Carga y validacion de la configuracion de proveedores al arranque (HU-S03)."""

import os
import re
import tomllib
from collections.abc import Callable, Container, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from availability_hotel.config.schema import AppConfig, AuthType, ProviderConfig
from availability_hotel.config.secrets import SecretError, SecretsClient

_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<default>[^}]*))?\}")
_SECRET_KEYS: Mapping[AuthType, tuple[str, ...]] = {
    AuthType.API_KEY: ("api_key",),
    AuthType.BASIC: ("username", "password"),
}

Secrets = Mapping[str, Mapping[str, Any]]


class ConfigError(RuntimeError):
    """Configuracion invalida; la aplicacion queda no lista (HTTP 503)."""


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    """Configuracion inmutable con los secretos resueltos una sola vez (RF-12)."""

    app: AppConfig
    secrets: Secrets


def _expand_env(value: Any, env: Mapping[str, str]) -> Any:
    """Expande `${VAR:-defecto}` en strings para variar URLs por entorno."""
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name, default = match["name"], match["default"]
            if name in env:
                return env[name]
            if default is None:
                raise ConfigError(f"variable de entorno '{name}' no definida")
            return default

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand_env(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item, env) for item in value]
    return value


def _describe_location(raw: Mapping[str, Any], loc: tuple[Any, ...]) -> str:
    if len(loc) >= 2 and loc[0] == "providers" and isinstance(loc[1], int):
        providers = raw.get("providers", [])
        provider_id = (
            providers[loc[1]].get("id", f"#{loc[1]}")
            if loc[1] < len(providers) and isinstance(providers[loc[1]], dict)
            else f"#{loc[1]}"
        )
        field = ".".join(str(part) for part in loc[2:]) or "(entrada)"
        return f"proveedor '{provider_id}' campo '{field}'"
    return "campo '" + ".".join(str(part) for part in loc) + "'"


def _format_validation_error(raw: Mapping[str, Any], exc: ValidationError) -> str:
    messages = []
    for error in exc.errors(include_url=False, include_input=False):
        where = _describe_location(raw, tuple(error["loc"]))
        if error["type"] == "less_than_equal":
            detail = f"el maximo es {error['ctx']['le']}"
        elif error["type"] == "missing":
            detail = "es obligatorio"
        else:
            detail = error["msg"]
        messages.append(f"{where}: {detail}")
    return "configuracion invalida: " + "; ".join(messages)


def parse_config(
    raw: Mapping[str, Any], adapters: Container[str], env: Mapping[str, str]
) -> AppConfig:
    """Valida el contenido del TOML; O(p) con p = proveedores (RNF-01)."""
    expanded = _expand_env(dict(raw), env)
    try:
        config = AppConfig.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(expanded, exc)) from None
    unknown = [p.id for p in config.providers if p.adapter not in adapters]
    if unknown:
        raise ConfigError(f"adaptador inexistente para los proveedores: {unknown}")
    return config


def read_toml(path: str | Path) -> dict[str, Any]:
    file = Path(path)
    try:
        with file.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError(f"archivo de configuracion inexistente: {file}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file}: TOML mal formado ({exc})") from None


def _validated_secret(
    provider: ProviderConfig, secrets_client: SecretsClient
) -> Mapping[str, Any]:
    secret_id = provider.auth.secret_id or ""
    try:
        secret = secrets_client.get_secret(secret_id)
    except SecretError as exc:
        raise ConfigError(f"proveedor '{provider.id}': {exc}") from None
    missing = [key for key in _SECRET_KEYS[provider.auth.type] if not secret.get(key)]
    if missing:
        raise ConfigError(
            f"proveedor '{provider.id}': secreto '{secret_id}' con forma invalida, "
            f"faltan las claves {missing}"
        )
    return secret


def load_secrets(config: AppConfig, secrets_client: SecretsClient) -> Secrets:
    """Lee los secretos de los proveedores habilitados con autenticacion."""
    return MappingProxyType(
        {
            provider.id: _validated_secret(provider, secrets_client)
            for provider in config.enabled_providers
            if provider.auth.type is not AuthType.NONE
        }
    )


def needs_secrets(config: AppConfig) -> bool:
    return any(p.auth.type is not AuthType.NONE for p in config.enabled_providers)


def load_config(
    path: str | Path,
    adapters: Container[str],
    secrets_factory: Callable[[], SecretsClient],
    env: Mapping[str, str] | None = None,
) -> LoadedConfig:
    """Carga TOML, valida y resuelve secretos; sin proveedores con auth no
    contacta Secrets Manager."""
    config = parse_config(read_toml(path), adapters, os.environ if env is None else env)
    if not needs_secrets(config):
        return LoadedConfig(app=config, secrets=MappingProxyType({}))
    return LoadedConfig(app=config, secrets=load_secrets(config, secrets_factory()))
