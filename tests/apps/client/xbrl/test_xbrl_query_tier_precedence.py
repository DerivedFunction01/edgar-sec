"""Tests proving tier-outcome precedence across split query scopes."""

import pytest

from edgar_sec.engine.xbrl.solve.core.query import QueryMode, QueryStatus
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from tests.apps.client.xbrl.xbrl_support import (
    _SYNTHETIC_ACCESSION,
    _canned_result,
    _create_synthetic_xbrl,
    _synthetic_fact,
)


@pytest.mark.parametrize(
    ("first_status", "second_status", "winner"),
    [
        (QueryStatus.CONFLICT, QueryStatus.VERIFIED, QueryStatus.VERIFIED),
        (QueryStatus.VERIFIED, QueryStatus.CONFLICT, QueryStatus.VERIFIED),
        (QueryStatus.CONFLICT, QueryStatus.REPORTED, QueryStatus.REPORTED),
        (QueryStatus.REPORTED, QueryStatus.CONFLICT, QueryStatus.REPORTED),
        (QueryStatus.DERIVED, QueryStatus.CONFLICT, QueryStatus.CONFLICT),
        (QueryStatus.CONFLICT, QueryStatus.DERIVED, QueryStatus.CONFLICT),
        (QueryStatus.AMBIGUOUS, QueryStatus.DERIVED, QueryStatus.DERIVED),
        (QueryStatus.DERIVED, QueryStatus.AMBIGUOUS, QueryStatus.DERIVED),
        (QueryStatus.AMBIGUOUS, QueryStatus.CONFLICT, QueryStatus.CONFLICT),
        (QueryStatus.CONFLICT, QueryStatus.AMBIGUOUS, QueryStatus.CONFLICT),
        (QueryStatus.UNAVAILABLE, QueryStatus.AMBIGUOUS, QueryStatus.AMBIGUOUS),
        (QueryStatus.AMBIGUOUS, QueryStatus.UNAVAILABLE, QueryStatus.AMBIGUOUS),
    ],
)
def test_tier_outcome_split_precedence_orders_statuses(
    monkeypatch: pytest.MonkeyPatch,
    first_status: QueryStatus,
    second_status: QueryStatus,
    winner: QueryStatus,
) -> None:
    """Verify the split precedence picks the higher status in either scope order."""
    xbrl = _create_synthetic_xbrl(
        (_synthetic_fact("us-gaap:Assets", 1.0, instant="2023-12-31"),)
    )
    scopes = (
        FactScope(accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31"),
        FactScope(
            accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31", unit="USD"
        ),
    )
    canned = {None: first_status, "USD": second_status}
    monkeypatch.setattr(
        xbrl._fiscal,
        "_execute_query",
        lambda term, mode, scope, arcs: _canned_result(canned[scope.unit], scope),
    )

    outcome, _, _ = xbrl._fiscal._tier_outcome(
        "term", QueryMode.REPORTED_ONLY, scopes, ()
    )
    assert outcome is not None
    assert outcome.status == winner


def test_tier_outcome_all_unavailable_returns_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a silent tier returns its first scope's result, not a later one."""
    xbrl = _create_synthetic_xbrl(
        (_synthetic_fact("us-gaap:Assets", 1.0, instant="2023-12-31"),)
    )
    scopes = (
        FactScope(accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31"),
        FactScope(
            accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31", unit="USD"
        ),
    )
    canned = [_canned_result(QueryStatus.UNAVAILABLE, scope) for scope in scopes]
    by_unit = {scope.unit: result for scope, result in zip(scopes, canned)}
    monkeypatch.setattr(
        xbrl._fiscal,
        "_execute_query",
        lambda term, mode, scope, arcs: by_unit[scope.unit],
    )

    outcome, first, _ = xbrl._fiscal._tier_outcome(
        "term", QueryMode.REPORTED_ONLY, scopes, ()
    )
    assert outcome is canned[0]
    assert first is canned[0]
