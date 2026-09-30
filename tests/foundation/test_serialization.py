"""Unit tests for foundation.serialization."""

from __future__ import annotations

import base64
import datetime
import decimal
import math

from edgar_sec.foundation.serialization import (
    canonical_hash,
    canonical_json,
    json_safe,
    safe_dumps,
)


def test_canonical_json_sorts_keys_and_is_stable() -> None:
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_scalars_pass_through() -> None:
    assert json_safe(None) is None
    assert json_safe(True) is True
    assert json_safe(7) == 7
    assert json_safe("text") == "text"


def test_decimal_keeps_exact_value_as_string() -> None:
    """A Decimal must not round-trip through float."""
    assert json_safe(decimal.Decimal("1.100")) == "1.100"


def test_bytes_become_base64() -> None:
    assert json_safe(b"ab") == base64.b64encode(b"ab").decode("ascii")


def test_non_finite_floats_become_none() -> None:
    """NaN/Infinity are not JSON; a strict parser would reject the document."""
    assert json_safe(math.nan) is None
    assert json_safe(math.inf) is None
    assert json_safe(-math.inf) is None
    assert json_safe(1.5) == 1.5


def test_datetimes_become_isoformat() -> None:
    assert json_safe(datetime.date(2026, 1, 2)) == "2026-01-02"
    assert json_safe(datetime.time(3, 4, 5)) == "03:04:05"


def test_nested_containers_are_converted_recursively() -> None:
    value = {
        "list": [decimal.Decimal("2.5"), {"deep": b"\x00"}],
        "tuple": (1, math.nan),
    }
    assert json_safe(value) == {
        "list": ["2.5", {"deep": "AA=="}],
        "tuple": [1, None],
    }


def test_unknown_type_falls_back_to_str() -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque"

    assert json_safe(Opaque()) == "opaque"


def test_safe_dumps_produces_encodable_json() -> None:
    assert safe_dumps({"n": math.nan, "d": decimal.Decimal("1.5")}) == (
        '{"n": null, "d": "1.5"}'
    )


def test_safe_dumps_preserves_key_order_where_canonical_json_sorts() -> None:
    """The two serializers differ on purpose.

    ``safe_dumps`` is for rendering, so it keeps insertion order -- which for a
    query result means the column order the caller asked for. ``canonical_json``
    sorts, because a digest must not depend on dict ordering. Collapsing them
    would mean either unsorted digests or alphabetical display order.
    """
    payload = {"zebra": 1, "apple": 2}
    assert safe_dumps(payload) == '{"zebra": 1, "apple": 2}'
    assert canonical_json(payload) == '{"apple":2,"zebra":1}'
