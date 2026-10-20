"""Cliente unico de AWS Secrets Manager (HU-S03 RF-08 a RF-15)."""

import json
from collections.abc import Callable
from types import MappingProxyType
from typing import Any, Protocol

from availability_hotel.config.settings import AppEnv, Settings

CONNECT_TIMEOUT_S = 2
READ_TIMEOUT_S = 5
MAX_ATTEMPTS = 2


class SecretError(RuntimeError):
    """Secreto inexistente, inaccesible o invalido; nunca incluye el valor."""

    def __init__(self, secret_id: str, reason: str) -> None:
        super().__init__(f"secreto '{secret_id}': {reason}")
        self.secret_id = secret_id
        self.reason = reason


class SecretsClient(Protocol):
    def get_secret(self, secret_id: str) -> MappingProxyType[str, Any]: ...


class AwsSecretsClient:
    """Adaptador sobre boto3; el resto del codigo no distingue entornos."""

    def __init__(self, client: Any, endpoint: str | None = None) -> None:
        self._client = client
        self._endpoint = endpoint

    def get_secret(self, secret_id: str) -> MappingProxyType[str, Any]:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            response = self._client.get_secret_value(SecretId=secret_id)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ClientError")
            raise SecretError(secret_id, f"no disponible ({code})") from None
        except BotoCoreError as exc:
            where = f" en {self._endpoint}" if self._endpoint else ""
            raise SecretError(
                secret_id, f"Secrets Manager inalcanzable{where} ({type(exc).__name__})"
            ) from None
        try:
            value = json.loads(response.get("SecretString") or "")
        except json.JSONDecodeError:
            raise SecretError(secret_id, "no es un JSON valido") from None
        if not isinstance(value, dict):
            raise SecretError(secret_id, "debe ser un objeto JSON")
        return MappingProxyType(value)


def build_secrets_client(
    settings: Settings, client_factory: Callable[..., Any] | None = None
) -> AwsSecretsClient:
    """Fabrica unica: LocalStack en local, cadena de credenciales de AWS en prod."""
    if client_factory is None:
        import boto3

        client_factory = boto3.client
    from botocore.config import Config

    config = Config(
        connect_timeout=CONNECT_TIMEOUT_S,
        read_timeout=READ_TIMEOUT_S,
        retries={"max_attempts": MAX_ATTEMPTS, "mode": "standard"},
    )
    if settings.app_env is AppEnv.LOCAL:
        client = client_factory(
            "secretsmanager",
            endpoint_url=settings.aws_endpoint_url,
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=config,
        )
        return AwsSecretsClient(client, settings.aws_endpoint_url)
    return AwsSecretsClient(client_factory("secretsmanager", config=config))
