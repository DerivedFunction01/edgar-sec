"""Pins for the operator-kit remainder homes (Wave 2B).
The error result, JSON-native conversion, artifacts root, options
gatherer, and spec-row closure live in ``operator_kit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from edgar_sec.apps.client.operator import (
    operator_company,
    operator_config,
    operator_drill,
    operator_fetch,
    operator_fund,
    operator_run_records,
    operator_selection,
    operator_state,
    operator_tools,
)
from edgar_sec.apps.client.operator import operator_kit as kit


def test_error_bindings_are_the_kit_home() -> None:
    assert operator_drill._error is kit.error_result
    assert operator_fetch._error is kit.error_result
    assert operator_fund._error is kit.error_result
    assert operator_selection._error is kit.error_result
    assert operator_tools.error_result is kit.error_result


def test_error_result_verdicts() -> None:
    result = kit.error_result("key_value", "invalid_options", "Title", "bad input")
    assert result.kind == "key_value"
    assert result.error_code == "invalid_options"
    assert result.data == {"message": "bad input"}
    assert len(result.components) == 1
    with_data = kit.error_result(
        "key_value", "invalid_options", "Title", "bad", data={"row": 3}
    )
    assert with_data.data == {"row": 3, "message": "bad"}


def test_config_error_result_divergence_pin() -> None:
    # operator_config's sibling stands: it hardcodes the kind and drops
    # the prose component entirely when the message is empty.
    local = operator_config._error_result("invalid_options", "Title", "")
    assert local.components == ()
    homed = kit.error_result("key_value", "invalid_options", "Title", "")
    assert len(homed.components) == 1


def test_json_native_bindings_and_verdicts() -> None:
    assert operator_fetch._json_native is kit.json_native
    assert operator_fund._json_native is kit.json_native
    value = {1: (Path("x"), [True, {"k": Path("y")}])}
    assert kit.json_native(value) == {"1": ["x", [True, {"k": "y"}]]}
    assert kit.json_native("plain") == "plain"


def test_artifacts_root_bindings_and_verdict() -> None:
    assert operator_fund._artifacts_root is kit.artifacts_root
    assert operator_run_records._artifacts_root is kit.artifacts_root
    session = SimpleNamespace(facade=SimpleNamespace(artifacts_root="/srv/art"))
    assert kit.artifacts_root(session) == Path("/srv/art")


def test_generic_bindings_are_the_kit_home() -> None:
    assert operator_company._generic is kit.gather_options
    assert operator_state._generic is kit.gather_options
    assert operator_tools._generic is kit.gather_options


def test_make_spec_verdicts() -> None:
    @dataclass
    class _Options:
        limit: int = 10

    spec = kit.make_spec()

    def _executor(session, options):  # pragma: no cover - identity only
        return None

    row = spec("op_id", "Label", _Options, "external", "key_value", _executor)
    assert row.id == "op_id"
    assert row.label == "Label"
    assert row.options_type is _Options
    assert row.effect == "external"
    assert row.requires == "none"
    assert row.result_kind == "key_value"
    assert row.hints == ("session_summary",)
    assert row.executor is _executor
