"""AOCI claim gates: rollforward-evidence and core-shape verdicts.

Cure 1 gates an equity-seated aoci claim with no rollforward
evidence; the Step 9 gate requires a standalone claim to carry
the family's core shape — a balance walk plus an AOCI subject.
"""

from __future__ import annotations

import re

from edgar_sec.engine.tables.extraction.form_test_specs import (
    AOCI_CLAIM_SHAPE_SPEC,
    form_test_specs_for,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.foundation.text.dates import FULL_DATE_STUB_RE

AOCI_STUB_EVIDENCE_MIN = 6.0
AOCI_GATE_MODE = "seat"

_BALANCE_STUB = re.compile(r"^(balance|aoci at|beginning balance|ending balance)\b")


def rollforward_evidence(score) -> bool:
    """Rollforward evidence: framing mass, or a movement-shaped stub."""
    framing = sum(
        score.by_channel.get(c, 0.0) for c in ("caption", "notehead", "lead_title")
    )
    return framing > 0 or score.by_channel.get("stub", 0.0) >= AOCI_STUB_EVIDENCE_MIN


def claim_shape(geometry) -> tuple[bool, bool]:
    """The AOCI core shape, as (walk, subject) legs over the geometry.
    Walk: both walk-spec anchors hit the stubs, or at least two dated
    balance stubs; Subject: a movement stub, lead phrase, or components."""
    stubs = [normalize_text(stub) for stub in geometry.stubs]
    walk_spec = next(
        (
            spec
            for spec in form_test_specs_for("aoci_rollforward")
            if spec.test_id == "aoci_beginning_ending_walk"
        ),
        None,
    )
    anchored = walk_spec is not None and (
        any(term in stub for stub in stubs for term in walk_spec.beginning)
        and any(term in stub for stub in stubs for term in walk_spec.ending)
    )
    dated = sum(
        1
        for stub in stubs
        if _BALANCE_STUB.match(stub) or FULL_DATE_STUB_RE.match(stub)
    )
    walk = anchored or dated >= 2
    spec = AOCI_CLAIM_SHAPE_SPEC
    grid = geometry.grid_text + " " + " ".join(geometry.headers)
    components = sum(1 for term in spec.component_terms if term in grid)
    subject = (
        spec.subject_phrase in geometry.stub_text
        or spec.lead_phrase in geometry.lead
        or components >= spec.min_components
    )
    return walk, subject


def aoci_gate_detail(claims: list[str], scores, geometry) -> str | None:
    """The gate detail when an AOCI gate removes the claim, else None.
    Cure 1 runs first; the claim-shape gate sees the claims Cure 1
    leaves standing, so at most one gate fires per geometry."""
    aoci_seated = AOCI_GATE_MODE == "any" or (
        AOCI_GATE_MODE == "seat" and "equity_statement" in claims
    )
    if (
        aoci_seated
        and "aoci_rollforward" in claims
        and not rollforward_evidence(scores["aoci_rollforward"])
    ):
        return "aoci: no rollforward evidence"
    if "aoci_rollforward" in claims and "equity_statement" not in claims:
        walk, subject = claim_shape(geometry)
        if not (walk and subject):
            missing = "walk" if not walk else "subject"
            return f"aoci: claim shape missing {missing}"
    return None
