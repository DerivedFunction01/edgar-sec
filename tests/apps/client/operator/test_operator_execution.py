"""Tests for the client operator execution core."""

from __future__ import annotations

import json

import pytest

from edgar_sec.apps.client.operator import operator_execution
from edgar_sec.foundation.runtime.render import Grid, ProseRow
from tests.apps.client.operator.test_operator import (
    _ProbeOptions,
    _probe_spec,
    _session,
)


def test_execute_custom_spec_and_context_refusal() -> None:
    session = _session()
    spec = _probe_spec()
    refused = operator_execution.execute_operation(spec, session, _ProbeOptions())
    assert refused.error_code == "missing_context"
    session.select_filing("A1")
    result = operator_execution.execute_operation(spec, session, _ProbeOptions(limit=1))
    assert result.error_code is None
    assert (result.total, result.shown) == (2, 1)
    assert isinstance(result.components[0], Grid)


def test_decode_options_coerces_and_refuses() -> None:
    spec = _probe_spec()
    assert operator_execution.decode_options(spec, {"limit": "3"}).limit == 3
    assert operator_execution.decode_options(spec, None).limit == 5
    with pytest.raises(ValueError):
        operator_execution.decode_options(spec, {"bogus": 1})
    result = operator_execution.execute_by_id(
        "probe", _session(), {"limit": "x"}, registry={"probe": spec}
    )
    assert result.error_code == "invalid_options"
    unknown = operator_execution.execute_by_id("nope", _session())
    assert unknown.error_code == "unknown_operation"
    assert json.dumps(unknown.to_payload())


def test_payload_message_carries_error_prose_only() -> None:
    session = _session()
    refused = operator_execution.execute_by_id("session_summary", session, {"bogus": 1})
    assert refused.error_code == "invalid_options"
    payload = refused.to_payload()
    assert payload["message"]
    assert "bogus" in payload["message"]
    ok = operator_execution.execute_by_id("session_summary", session, {})
    assert ok.error_code is None
    assert ok.to_payload()["message"] is None


def test_prose_result_kind_serializes() -> None:
    result = operator_execution.OpResult(
        kind="prose",
        title="Note",
        components=(ProseRow("hello"),),
        data={"text": "hello"},
        total=1,
        shown=1,
    )
    assert json.loads(json.dumps(result.to_payload()))["data"] == {"text": "hello"}
