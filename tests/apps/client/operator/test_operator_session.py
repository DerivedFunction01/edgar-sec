"""Tests for the client operator session state."""

from __future__ import annotations

from edgar_sec.apps.client.operator import operator_session
from tests.apps.client.operator.test_operator import _FakeFacade, _FakeResult


def test_session_state_and_lazy_facade() -> None:
    facade = _FakeFacade()
    session = operator_session.ClientSession(facade=facade)
    assert session.facade is facade
    assert facade.calls == []
    fresh = operator_session.ClientSession()
    assert fresh._facade is None
    result = _FakeResult(["A1", "A2"])
    working = session.add_set("tech", ["A1", "A2", "A1"], result=result)
    assert working.accessions == frozenset({"A1", "A2"})
    assert working.result is result
    assert session.current_set is working
    assert session.satisfies("selection")
    assert not session.satisfies("current_filing")
    session.select_filing("A1", aggregate=result)
    assert session.satisfies("current_filing")
    assert session.last_run_record == ""
