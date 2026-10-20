import io
import json
import logging
from decimal import Decimal

from availability_hotel.core.logging import (
    REDACTED,
    configure_logging,
    correlation_id_var,
    get_logger,
    log_event,
    redact,
    shutdown_logging,
    truncate,
)


def _capture(level="INFO"):
    stream = io.StringIO()
    configure_logging(level, stream=stream)
    return stream


def _lines(stream):
    shutdown_logging()
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_redact_nested_sensitive_keys():
    data = {
        "api_key": "k",
        "headers": {"Authorization": "Basic x", "x-api-key": "k2", "ok": 1},
        "items": [{"password": "p"}],
    }
    assert redact(data) == {
        "api_key": REDACTED,
        "headers": {"Authorization": REDACTED, "x-api-key": REDACTED, "ok": 1},
        "items": [{"password": REDACTED}],
    }


def test_truncate():
    assert truncate("abc", 5) == "abc"
    assert truncate("abcdef", 3) == "abc...<truncated>"


def test_json_line_with_correlation_and_fields():
    stream = _capture()
    token = correlation_id_var.set("corr-1")
    try:
        log_event(
            get_logger("t"),
            "provider_call",
            provider_id="provider_a",
            cost=Decimal("0.01"),
            api_key="should-not-appear",
        )
    finally:
        correlation_id_var.reset(token)
    [line] = _lines(stream)
    assert line["event"] == "provider_call"
    assert line["correlation_id"] == "corr-1"
    assert line["provider_id"] == "provider_a"
    assert line["cost"] == "0.01"
    assert line["api_key"] == REDACTED
    assert "should-not-appear" not in stream.getvalue()


def test_level_filter_and_exception_trace():
    stream = _capture("WARNING")
    logger = get_logger("t")
    log_event(logger, "hidden")
    try:
        raise ValueError("boom")
    except ValueError:
        log_event(logger, "failure", logging.ERROR, exc_info=True)
    [line] = _lines(stream)
    assert line["event"] == "failure"
    assert "ValueError: boom" in line["exception"]


def test_uvicorn_loggers_propagate_to_root():
    stream = _capture()
    logging.getLogger("uvicorn.error").addHandler(logging.NullHandler())
    configure_logging("INFO", stream=stream)
    assert logging.getLogger("uvicorn.error").handlers == []
    logging.getLogger("uvicorn.error").info("started")
    [line] = _lines(stream)
    assert line["logger"] == "uvicorn.error"


def test_non_serializable_values_do_not_break_logging():
    stream = _capture()
    log_event(get_logger("t"), "odd", value=object())
    [line] = _lines(stream)
    assert line["value"].startswith("<object")
