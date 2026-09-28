"""Unit tests for foundation.serialization."""

from __future__ import annotations

import pytest

from edgar_sec.foundation.serialization import canonical_hash, canonical_json


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_canonical_hash_is_key_order_independent() -> None:
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_canonical_hash_differs_for_different_payloads() -> None:
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_canonical_json_rejects_unserializable_values() -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_json({"key": object()})
