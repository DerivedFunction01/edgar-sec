"""Normalization regression goldens.

A golden pins the *outcome* of the normalization chain for a committed input: the
cover region it found, the body anchor it chose, the closing span, the evaluator's
verdict, and the stage order it ran. Any of those changing is a behaviour change
that should be a deliberate, reviewed edit to the fixture rather than a silent
diff in a test run.

The inputs are synthetic. That is a deliberate limit, not an oversight: real
filing fixtures and the golden comparison against promoted outputs are M6.3/M6.4
and are deferred. A synthetic input still catches the failure this guards against
— a refactor silently moving a boundary, dropping a stage, or changing what the
form evaluator concludes — and it stays offline, deterministic, and fast.

The stage order is pinned as well as the results because order is the load-bearing
invariant: reflow must not run before the boundary is detected, or the solver
would be handed a stale coordinate frame.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.engine.forms.plugins.registry import get_plugin

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "document_storage"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _observed(data: dict[str, Any]) -> dict[str, Any]:
    """Run the chain and report everything the golden pins."""
    result = normalize_document(data["source_text"], form=data["form"])
    inference = result.checkmark_inference
    decision = get_plugin(data["form"]).evaluator(result.text)
    body = result.body_start
    closing = result.closing_span
    analysis = result.page_analysis
    return {
        "representation": result.representation,
        "family": result.family,
        "cover_boundary_method": result.cover_boundary.method.value,
        "cover_start_detected_line": result.cover_start_detected_line,
        "cover_boundary_detected_line": result.cover_boundary_detected_line,
        "cover_boundary_confidence": round(result.cover_boundary.confidence, 4),
        "body_anchor_type": None if body is None else body.anchor_type,
        "body_first_unit_line": None if body is None else body.first_unit_line,
        "closing_kind": None if closing is None else closing.kind,
        "closing_start_line": None if closing is None else closing.start_line,
        "decision_action": decision.action.value,
        "checkmark_status": (
            None if inference is None else getattr(inference.status, "value", None)
        ),
        "page_marker_count": 0 if analysis is None else len(analysis.markers),
        "word_count": len(result.text.split()),
        "stage_order": [entry["stage"] for entry in result.stage_trace],
        # The table-protection invariants hold for every input, so they are part of
        # every golden rather than a separate test: a tagged table must come out
        # intact and no sentinel token may survive into stored text.
        "table_survives": "<TABLE>" in result.text,
        "no_sentinels_leaked": "__SEC_TBL_" not in result.text,
    }


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURE_DIR.glob("*.json")))
def test_normalization_golden(name: str) -> None:
    data = _load(name)
    assert _observed(data) == data["expectations"]


def test_the_golden_fixture_is_self_describing() -> None:
    data = _load("annual_10k_normalization.json")
    assert data["form"]
    assert data["source_text"].strip()
    assert set(data["expectations"]) == {
        "representation",
        "family",
        "cover_boundary_method",
        "cover_start_detected_line",
        "cover_boundary_detected_line",
        "cover_boundary_confidence",
        "body_anchor_type",
        "body_first_unit_line",
        "closing_kind",
        "closing_start_line",
        "decision_action",
        "checkmark_status",
        "page_marker_count",
        "word_count",
        "stage_order",
        "table_survives",
        "no_sentinels_leaked",
    }


def test_the_boundary_is_detected_before_reflow() -> None:
    """The load-bearing ordering invariant, stated directly."""
    data = _load("annual_10k_normalization.json")
    result = normalize_document(data["source_text"], form=data["form"])
    stages = [entry["stage"] for entry in result.stage_trace]
    assert stages.index("cover_boundary") < stages.index("after_reflow")
    assert stages.index("after_final_whitespace") < stages.index("before_reflow")


def test_normalization_is_deterministic() -> None:
    """Two runs over the same input must agree, or a golden is meaningless."""
    data = _load("annual_10k_normalization.json")
    assert _observed(data) == _observed(data)
