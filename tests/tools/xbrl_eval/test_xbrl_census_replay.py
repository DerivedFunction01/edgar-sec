"""Tests for the census faithful-tier replay."""

from edgar_sec.tools.xbrl_eval.xbrl_census_replay import classify, replay_faithful


def _rec(status: str, value: float | None = None, candidates=()) -> dict:
    """One recorded scope result in the census record shape."""
    return {
        "status": status,
        "value": value,
        "candidates": list(candidates),
        "tier": "",
        "reported_qname": None,
        "equivalents": [],
        "scope": {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "instant": None,
            "unit": None,
            "span": 365,
            "kind": "duration",
        },
    }


def test_replay_prefers_conflict_over_ambiguous_within_a_tier() -> None:
    """The split precedence: a faithful tier's CONFLICT outranks its AMBIGUOUS."""
    records = [_rec("AMBIGUOUS"), _rec("CONFLICT", value=-5.0)]
    faithful = replay_faithful(records, ())
    assert faithful is not None
    assert faithful["status"] == "CONFLICT"
    facade = _rec("CONFLICT", value=-5.0)
    assert classify(facade, faithful) == "honest-faithful"


def test_replay_keeps_verified_above_conflict() -> None:
    """VERIFIED stays on top of the split precedence inside a tier."""
    records = [_rec("CONFLICT", value=-5.0), _rec("VERIFIED", value=7.0)]
    faithful = replay_faithful(records, ())
    assert faithful is not None
    assert faithful["status"] == "VERIFIED"
    assert classify(_rec("VERIFIED", value=7.0), faithful) == "correct"


def test_replay_duration_success_is_final() -> None:
    """A duration-tier success ends the replay; instants are not consulted."""
    records = [_rec("REPORTED", value=3.0), _rec("UNAVAILABLE")]
    faithful = replay_faithful(records, ())
    assert faithful is not None
    assert faithful["status"] == "REPORTED"


def test_classify_adverse_shapes() -> None:
    """Success/failure disagreements classify into the adverse classes."""
    faithful = _rec("REPORTED", value=3.0)
    assert classify(_rec("UNAVAILABLE"), faithful) == "refused"
    assert classify(_rec("REPORTED", value=4.0), faithful) == "wrong-value"
    honest = _rec("AMBIGUOUS")
    assert classify(_rec("REPORTED", value=1.0), honest) == "wrong-span"
