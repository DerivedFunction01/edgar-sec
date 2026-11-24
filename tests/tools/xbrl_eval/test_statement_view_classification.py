"""Statement-view classification rules."""

from __future__ import annotations

from typing import Any

from edgar_sec.tools.xbrl_eval.statement_view_classification import classify_record
from edgar_sec.tools.xbrl_eval.statement_view_vocabulary import (
    BLOCKED,
    FAITHFUL,
    HONEST,
    MECH_FACE,
    MECH_PARSE,
    MECH_ROOT,
    MECH_UNVERIFIED,
)


def _record(cells: dict[str, Any], *, statement: bool) -> dict[str, Any]:
    """A minimal driver record carrying the given cells."""
    return {"analysis": {"statement": statement}, "cells": cells}


def test_classify_empty_statement_graph_blocks_only_for_statement_filings() -> None:
    """An empty income graph is a missing root on statement filings only."""
    cell = {
        "kind": "statement",
        "error": None,
        "nodes": 0,
        "root": None,
        "valued_nodes": 0,
    }
    verdict = classify_record(
        _record({"statements.income_statement": cell}, statement=True)
    )
    assert verdict["statements.income_statement"] == {
        "classification": BLOCKED,
        "mechanism": MECH_ROOT,
    }
    verdict = classify_record(
        _record({"statements.income_statement": cell}, statement=False)
    )
    assert verdict["statements.income_statement"]["classification"] == HONEST


def test_classify_unavailable_statement_is_honest_even_on_statement_filings() -> None:
    """An explicit UNAVAILABLE posture is honest, not a missing root."""
    cell = {
        "kind": "statement",
        "error": None,
        "nodes": 0,
        "root": None,
        "valued_nodes": 0,
        "status": "UNAVAILABLE",
    }
    verdict = classify_record(
        _record({"statements.comprehensive_income_statement": cell}, statement=True)
    )
    assert (
        verdict["statements.comprehensive_income_statement"]["classification"] == HONEST
    )


def test_classify_scalar_verification_and_cover_parity() -> None:
    """Unverified served values and cover mismatches block; parity is faithful."""
    cells = {
        "financials.revenue": {
            "kind": "scalar",
            "error": None,
            "value": 5.0,
            "in_filed": False,
            "span_class": None,
            "span_error": None,
        },
        "financials.capex": {
            "kind": "scalar",
            "error": None,
            "value": None,
            "in_filed": None,
            "span_class": None,
            "span_error": None,
        },
        "statements.cover": {
            "kind": "cover",
            "error": None,
            "facts": 3,
            "dei_filed": 4,
        },
    }
    verdict = classify_record(_record(cells, statement=True))
    assert verdict["financials.revenue"] == {
        "classification": BLOCKED,
        "mechanism": MECH_UNVERIFIED,
    }
    assert verdict["financials.capex"]["classification"] == HONEST
    assert verdict["statements.cover"] == {
        "classification": BLOCKED,
        "mechanism": MECH_PARSE,
    }
    cells["statements.cover"] = {
        "kind": "cover",
        "error": None,
        "facts": 4,
        "dei_filed": 4,
    }
    verdict = classify_record(_record(cells, statement=True))
    assert verdict["statements.cover"]["classification"] == FAITHFUL


def test_classify_catalog_face_missing_blocks() -> None:
    """A served scalar missing from its statement face blocks the catalog cell."""
    cell = {
        "kind": "catalog",
        "error": None,
        "role_count": 12,
        "violations": [],
        "exceptions": [],
        "face_totals": [
            {"family": "IncomeStatement", "metric": "revenue", "status": "missing"}
        ],
    }
    verdict = classify_record(_record({"statements.catalog": cell}, statement=True))
    assert verdict["statements.catalog"] == {
        "classification": BLOCKED,
        "mechanism": MECH_FACE,
    }
