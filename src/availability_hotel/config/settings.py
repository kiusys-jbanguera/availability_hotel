"""Variables de entorno de la aplicacion (HU-S03 RF-09 a RF-11, HU-S04 RF-05)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_PROVIDERS_CONFIG = "config/providers.toml"
DEFAULT_REGION = "us-east-1"
LOCALSTACK_TEST_CREDENTIAL = "test"


class AppEnv(StrEnum):
    LOCAL = "local"
    PROD = "prod"


class SettingsError(RuntimeError):
    """Error de entorno que aborta el arranque del proceso."""


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: AppEnv
    providers_config: str = DEFAULT_PROVIDERS_CONFIG
    log_level: str = "INFO"
    aws_endpoint_url: str | None = None
    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        raw_env = env.get("APP_ENV", "").strip()
        if not raw_env:
            raise SettingsError("APP_ENV es obligatorio: use 'local' o 'prod'")
        try:
            app_env = AppEnv(raw_env)
        except ValueError as exc:
            raise SettingsError(
                f"APP_ENV='{raw_env}' no es valido: use 'local' o 'prod'"
            ) from exc
        common = {
            "app_env": app_env,
            "providers_config": env.get("PROVIDERS_CONFIG", DEFAULT_PROVIDERS_CONFIG),
            "log_level": env.get("LOG_LEVEL", "INFO").upper(),
        }
        if app_env is AppEnv.PROD:
            return cls(**common)
        endpoint = env.get("AWS_ENDPOINT_URL", "").strip()
        if not endpoint:
            raise SettingsError("APP_ENV=local requiere AWS_ENDPOINT_URL (LocalStack)")
        return cls(
            **common,
            aws_endpoint_url=endpoint,
            aws_region=env.get("AWS_DEFAULT_REGION", DEFAULT_REGION),
            aws_access_key_id=env.get("AWS_ACCESS_KEY_ID", LOCALSTACK_TEST_CREDENTIAL),
            aws_secret_access_key=env.get(
                "AWS_SECRET_ACCESS_KEY", LOCALSTACK_TEST_CREDENTIAL
            ),
        )
