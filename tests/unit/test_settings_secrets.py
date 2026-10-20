import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from availability_hotel.config.secrets import (
    AwsSecretsClient,
    SecretError,
    build_secrets_client,
)
from availability_hotel.config.settings import AppEnv, Settings, SettingsError


def test_app_env_is_required():
    with pytest.raises(SettingsError, match="APP_ENV es obligatorio"):
        Settings.from_env({})


def test_unknown_app_env_aborts():
    with pytest.raises(SettingsError, match="'staging' no es valido"):
        Settings.from_env({"APP_ENV": "staging"})


def test_local_requires_endpoint():
    with pytest.raises(SettingsError, match="AWS_ENDPOINT_URL"):
        Settings.from_env({"APP_ENV": "local"})


def test_local_settings_with_defaults():
    settings = Settings.from_env(
        {"APP_ENV": "local", "AWS_ENDPOINT_URL": "http://localstack:4566"}
    )
    assert settings.app_env is AppEnv.LOCAL
    assert settings.aws_region == "us-east-1"
    assert settings.aws_access_key_id == "test"
    assert settings.log_level == "INFO"


def test_prod_settings_ignore_localstack_variables():
    settings = Settings.from_env(
        {
            "APP_ENV": "prod",
            "AWS_ENDPOINT_URL": "http://localstack:4566",
            "AWS_ACCESS_KEY_ID": "test",
            "LOG_LEVEL": "debug",
        }
    )
    assert settings.aws_endpoint_url is None
    assert settings.aws_access_key_id is None
    assert settings.log_level == "DEBUG"


class RecordingFactory:
    def __init__(self, client=None):
        self.calls = []
        self.client = client

    def __call__(self, service, **kwargs):
        self.calls.append((service, kwargs))
        return self.client


def test_local_client_uses_localstack_parameters():
    factory = RecordingFactory()
    settings = Settings.from_env(
        {"APP_ENV": "local", "AWS_ENDPOINT_URL": "http://localstack:4566"}
    )
    build_secrets_client(settings, factory)
    [(service, kwargs)] = factory.calls
    assert service == "secretsmanager"
    assert kwargs["endpoint_url"] == "http://localstack:4566"
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["aws_access_key_id"] == "test"
    assert kwargs["aws_secret_access_key"] == "test"


def test_prod_client_has_no_endpoint_nor_static_keys():
    factory = RecordingFactory()
    build_secrets_client(Settings.from_env({"APP_ENV": "prod"}), factory)
    [(service, kwargs)] = factory.calls
    assert service == "secretsmanager"
    assert set(kwargs) == {"config"}


def test_default_factory_builds_real_boto3_client():
    settings = Settings.from_env(
        {"APP_ENV": "local", "AWS_ENDPOINT_URL": "http://127.0.0.1:1"}
    )
    client = build_secrets_client(settings)
    assert client._client.meta.endpoint_url == "http://127.0.0.1:1"


class StubBoto:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def get_secret_value(self, SecretId):
        if self.error:
            raise self.error
        return self.response


def test_get_secret_parses_json():
    client = AwsSecretsClient(StubBoto({"SecretString": '{"api_key": "x"}'}))
    assert client.get_secret("provider/a")["api_key"] == "x"


@pytest.mark.parametrize(
    ("stub", "message"),
    [
        (
            StubBoto(
                error=ClientError(
                    {"Error": {"Code": "ResourceNotFoundException"}}, "GetSecretValue"
                )
            ),
            "ResourceNotFoundException",
        ),
        (
            StubBoto(
                error=ClientError(
                    {"Error": {"Code": "AccessDeniedException", "Message": "s3cr3t"}},
                    "GetSecretValue",
                )
            ),
            "AccessDeniedException",
        ),
        (
            StubBoto(error=EndpointConnectionError(endpoint_url="http://ls:4566")),
            "inalcanzable en http://ls:4566",
        ),
        (StubBoto({"SecretString": "not-json"}), "JSON valido"),
        (StubBoto({"SecretString": "[1, 2]"}), "objeto JSON"),
    ],
)
def test_get_secret_errors_name_secret_without_value(stub, message):
    client = AwsSecretsClient(stub, endpoint="http://ls:4566")
    with pytest.raises(SecretError) as exc:
        client.get_secret("provider/a")
    assert "provider/a" in str(exc.value)
    assert message in str(exc.value)
    assert "s3cr3t" not in str(exc.value)
