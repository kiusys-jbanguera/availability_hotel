from datetime import date
from decimal import Decimal

import pytest

from availability_hotel.core.extract import (
    AmountParser,
    FormatError,
    as_list,
    get_path,
    parse_date,
)

PAYLOAD = {"a": {"b": [{"c": 1}, {"c": 2}]}, "s": "text"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [("a.b.1.c", 2), ("a.b.0", {"c": 1}), ("a.x", None), ("a.b.9", None)],
)
def test_get_path(path, expected):
    assert get_path(PAYLOAD, path) == expected


def test_get_path_non_numeric_index_and_strings():
    assert get_path(PAYLOAD, "a.b.x") is None
    assert get_path(PAYLOAD, "s.0", "default") == "default"


def test_as_list():
    assert as_list(None) == []
    assert as_list([1]) == [1]
    assert as_list({"k": 1}) == [{"k": 1}]


@pytest.mark.parametrize("value", ["01/11/2026", "20261101", " 01/11/2026 "])
def test_parse_date_declared_formats(value):
    assert parse_date(value, ["%d/%m/%Y", "%Y%m%d"]) == date(2026, 11, 1)


def test_parse_date_invalid():
    with pytest.raises(FormatError):
        parse_date("2026-11-01", ["%d/%m/%Y"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,50", Decimal("1234.50")),
        ("1.234", Decimal("1234")),
        ("455,90", Decimal("455.90")),
        ("1234567,1", Decimal("1234567.1")),
        (12, Decimal("12")),
        (Decimal("3.10"), Decimal("3.10")),
    ],
)
def test_amount_parser_european(raw, expected):
    assert AmountParser(".", ",").parse(raw) == expected


@pytest.mark.parametrize("raw", ["1,234.50", "12.34.5", "abc", "", "1.23,4,5"])
def test_amount_parser_rejects_non_declared_format(raw):
    with pytest.raises(FormatError):
        AmountParser(".", ",").parse(raw)


def test_amount_parser_default_format():
    parser = AmountParser()
    assert parser.parse("119.00") == Decimal("119.00")
    with pytest.raises(FormatError):
        parser.parse("1,000.00")
