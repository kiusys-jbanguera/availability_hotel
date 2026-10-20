import time
import tomllib
from decimal import Decimal

import pytest

from availability_hotel.config.loader import (
    ConfigError,
    load_config,
    parse_config,
    read_toml,
)
from availability_hotel.config.schema import RateLimitAlgorithm
from availability_hotel.providers import registry
from tests.conftest import CONFIG_FILE, FakeSecretsClient


def _raw():
    return tomllib.loads(CONFIG_FILE.read_text())


def _provider(raw, provider_id):
    return next(p for p in raw["providers"] if p["id"] == provider_id)


def test_repository_config_is_valid_and_loads_secrets_once():
    secrets = FakeSecretsClient()
    loaded = load_config(CONFIG_FILE, registry, lambda: secrets, env={})
    assert [p.id for p in loaded.app.enabled_providers] == [
        "provider_a",
        "provider_b",
        "provider_c",
    ]
    assert sorted(secrets.calls) == ["provider/a", "provider/b", "provider/c"]
    a, b, c = loaded.app.providers
    assert a.rate_limit.enabled and a.rate_limit.requests == 10
    assert a.rate_limit.algorithm is RateLimitAlgorithm.SLIDING_WINDOW
    assert a.billing.cost_per_request == Decimal("0.0050")
    assert not b.pricing.taxes_included and b.pricing.tax_rate == Decimal("0.19")
    assert c.timeout_s == 2.0 and not c.rate_limit.enabled
    assert c.business_errors is not None
    assert loaded.app.search.timeout_s == 2.0
    with pytest.raises(TypeError):
        loaded.secrets["provider_a"]["api_key"] = "x"


def test_env_expansion_for_base_url():
    config = parse_config(
        _raw(), registry, env={"PROVIDER_A_BASE_URL": "http://mock-provider-a:9000"}
    )
    assert config.providers[0].base_url == "http://mock-provider-a:9000"
    assert config.providers[1].base_url == "http://localhost:9002"


def test_env_expansion_without_default_requires_variable():
    raw = _raw()
    _provider(raw, "provider_a")["base_url"] = "${MISSING_URL}"
    with pytest.raises(ConfigError, match="MISSING_URL"):
        parse_config(raw, registry, env={})


def test_timeout_above_maximum_is_rejected():
    raw = _raw()
    _provider(raw, "provider_b")["timeout_s"] = 5
    with pytest.raises(ConfigError) as exc:
        parse_config(raw, registry, env={})
    assert "proveedor 'provider_b' campo 'timeout_s': el maximo es 2.0" in str(
        exc.value
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.pop("adapter"), "campo 'adapter': es obligatorio"),
        (lambda p: p.update(enabled="maybe"), "campo 'enabled'"),
        (lambda p: p["auth"].pop("header"), "auth.header es obligatorio"),
        (lambda p: p["auth"].pop("secret_id"), "auth.secret_id es obligatorio"),
        (
            lambda p: p["rate_limit"].pop("requests"),
            "rate_limit.requests y rate_limit.per_seconds",
        ),
        (lambda p: p.update(base_url="ftp://x"), "campo 'base_url'"),
    ],
)
def test_invalid_fields_have_clear_messages(mutate, message):
    raw = _raw()
    mutate(_provider(raw, "provider_a"))
    with pytest.raises(ConfigError, match="provider_a") as exc:
        parse_config(raw, registry, env={})
    assert message in str(exc.value)


def test_tax_rate_required_when_taxes_not_included():
    raw = _raw()
    _provider(raw, "provider_b")["pricing"].pop("tax_rate")
    with pytest.raises(ConfigError, match="pricing.tax_rate es obligatorio"):
        parse_config(raw, registry, env={})


def test_duplicated_ids():
    raw = _raw()
    raw["providers"].append(dict(_provider(raw, "provider_c")))
    with pytest.raises(ConfigError, match="duplicados: \\['provider_c'\\]"):
        parse_config(raw, registry, env={})


def test_unknown_adapter():
    raw = _raw()
    _provider(raw, "provider_c")["adapter"] = "provider_zz"
    with pytest.raises(ConfigError, match="adaptador inexistente.*provider_c"):
        parse_config(raw, registry, env={})


def test_search_timeout_is_application_level():
    raw = _raw()
    raw["search"]["timeout_s"] = 3
    with pytest.raises(ConfigError, match="campo 'search.timeout_s': el maximo"):
        parse_config(raw, registry, env={})


def test_missing_secret_names_provider_and_secret_without_values(tmp_path):
    secrets = FakeSecretsClient({"provider/b": {"username": "u", "password": "p"}})
    with pytest.raises(ConfigError) as exc:
        load_config(CONFIG_FILE, registry, lambda: secrets, env={})
    assert "provider_a" in str(exc.value) and "provider/a" in str(exc.value)


def test_secret_with_invalid_shape():
    secrets = FakeSecretsClient(
        {
            "provider/a": {"api_key": "k"},
            "provider/b": {"username": "u", "password": "super-secret"},
            "provider/c": {"token": "wrong"},
        }
    )
    with pytest.raises(ConfigError) as exc:
        load_config(CONFIG_FILE, registry, lambda: secrets, env={})
    message = str(exc.value)
    assert "provider_c" in message and "['api_key']" in message
    assert "wrong" not in message and "super-secret" not in message


def _write(tmp_path, raw_text):
    path = tmp_path / "providers.toml"
    path.write_text(raw_text)
    return path


def test_all_disabled_does_not_contact_secrets_manager(tmp_path):
    text = CONFIG_FILE.read_text().replace("enabled = true", "enabled = false")

    def factory():
        raise AssertionError("no debe construirse el cliente de secretos")

    loaded = load_config(_write(tmp_path, text), registry, factory, env={})
    assert loaded.app.enabled_providers == ()
    assert loaded.secrets == {}


def test_disabled_provider_secret_not_required(tmp_path):
    raw = CONFIG_FILE.read_text()
    first = raw.index("enabled = true")
    text = raw[:first] + "enabled = false" + raw[first + len("enabled = true") :]
    secrets = FakeSecretsClient(
        {k: v for k, v in FakeSecretsClient().secrets.items() if k != "provider/a"}
    )
    loaded = load_config(_write(tmp_path, text), registry, lambda: secrets, env={})
    assert [p.id for p in loaded.app.enabled_providers] == ["provider_b", "provider_c"]
    assert "provider/a" not in secrets.calls


def test_new_provider_entry_with_existing_adapter(tmp_path):
    extra = """
[[providers]]
id = "provider_d"
enabled = true
adapter = "provider_c"
base_url = "http://localhost:9004"

[providers.auth]
type = "none"
"""
    path = _write(tmp_path, CONFIG_FILE.read_text() + extra)
    loaded = load_config(path, registry, FakeSecretsClient, env={})
    assert [p.id for p in loaded.app.enabled_providers][-1] == "provider_d"
    assert "provider_d" not in loaded.secrets


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="inexistente"):
        read_toml(tmp_path / "nope.toml")


def test_malformed_toml_reports_path_and_line(tmp_path):
    path = _write(tmp_path, "[search]\ntimeout_s = = 2\n")
    with pytest.raises(ConfigError) as exc:
        read_toml(path)
    assert str(path) in str(exc.value) and "line 2" in str(exc.value)


def test_thousand_providers_load_linearly():
    entries = [
        {
            "id": f"p{i}",
            "enabled": True,
            "adapter": "provider_c",
            "base_url": f"http://p{i}.local",
            "auth": {"type": "none"},
        }
        for i in range(1000)
    ]
    start = time.perf_counter()
    config = parse_config({"providers": entries}, registry, env={})
    assert len(config.enabled_providers) == 1000
    assert time.perf_counter() - start < 2
