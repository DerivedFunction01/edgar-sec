"""AOCI claim gates: rollforward-evidence and core-shape verdicts.

Cure 1 gates an equity-seated aoci claim with no rollforward evidence,
unless the geometry carries the family's core shape; the Step 9 gate
requires that core shape — a balance walk plus an AOCI subject.
"""

from __future__ import annotations

import re

from edgar_sec.engine.tables.extraction.form_specs.aoci_claim_shape_specs import (
    AOCI_CLAIM_SHAPE_SPEC,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    form_test_specs_for,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.foundation.text.date_patterns import FULL_DATE_STUB_RE

AOCI_STUB_EVIDENCE_MIN = 6.0
AOCI_GATE_MODE = "seat"

_BALANCE_STUB = re.compile(r"^(balance|aoci at|beginning balance|ending balance)\b")

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

_EQUITY_ACCOUNT_TERMS = (
    "common stock",
    "preferred stock",
    "common shares",
    "retained earnings",
    "accumulated deficit",
    "paid-in capital",
    "paid in capital",
    "treasury stock",
    "total equity",
    "shareholders' equity",
    "shareholders’ equity",
    "stockholders' equity",
    "total shareholders",
    "total stockholders",
    "noncontrolling interest",
    "non-controlling interest",
)

_STATEMENT_SECTION_TERMS = (
    "operating activities",
    "investing activities",
    "financing activities",
)


def _dated_balance(text: str) -> bool:
    """A balance stub or header carrying a month name."""
    return text.startswith(("balance", "beginning balance", "ending balance")) and any(
        m in text for m in _MONTHS
    )


def _movement_stubs(stubs: list[str]) -> int:
    """Stub lines carrying OCI movement vocabulary."""
    return sum(
        1
        for stub in stubs
        if "reclassif" in stub or "other comprehensive" in stub or "unrealized" in stub
    )


def rollforward_evidence(score) -> bool:
    """Rollforward evidence: framing mass, or a movement-shaped stub."""
    framing = sum(
        score.by_channel.get(c, 0.0) for c in ("caption", "notehead", "lead_title")
    )
    return framing > 0 or score.by_channel.get("stub", 0.0) >= AOCI_STUB_EVIDENCE_MIN


def claim_shape(geometry) -> tuple[bool, bool]:
    """The AOCI core shape, as (walk, subject) legs over the geometry.
    Walk: the walk-spec anchors, two dated balance stubs, or a priced
    dialect; Subject: a movement stub, lead phrase, or components."""
    stubs = [normalize_text(stub) for stub in geometry.stubs]
    headers = [normalize_text(header) for header in geometry.headers]
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
    aoci_dated = sum(
        1
        for stub in stubs
        if stub.startswith("aoci balance") or stub.startswith("aoci at")
    )
    # Dialects: dated aoci stubs; the beginning-of-period pair;
    # a dated stub balance with the beginning balance in the headers;
    # a bare-date walk (dated stub, dated header, movement stubs).
    walk = (
        anchored
        or dated >= 2
        or (aoci_dated >= 1 and any("balance" in stub for stub in stubs))
        or (
            "balance at beginning of period" in stubs
            and any(
                stub.startswith("accumulated other comprehensive") for stub in stubs
            )
        )
        or (
            any(_dated_balance(stub) for stub in stubs)
            and any(_dated_balance(header) for header in headers)
        )
        or (
            any(FULL_DATE_STUB_RE.match(stub) for stub in stubs)
            and any(FULL_DATE_STUB_RE.match(header) for header in headers)
            and _movement_stubs(stubs) >= 2
        )
    )
    spec = AOCI_CLAIM_SHAPE_SPEC
    grid = geometry.grid_text + " " + " ".join(geometry.headers)
    components = sum(1 for term in spec.component_terms if term in grid)
    subject = (
        spec.subject_phrase in geometry.stub_text
        or spec.lead_phrase in geometry.lead
        or components >= spec.min_components
    )
    return walk, subject


def component_grid(geometry) -> bool:
    """The component-grid form: an AOCI balance walk over component
    columns whose stubs carry the OCI movement vocabulary."""
    stubs = [normalize_text(stub) for stub in geometry.stubs]
    walk, _ = claim_shape(geometry)
    if not walk:
        return False
    movements = _movement_stubs(stubs)
    framing = "other comprehensive" in normalize_text(geometry.lead) or (
        geometry.note_title is not None
        and "comprehensive" in normalize_text(geometry.note_title)
    )
    if not (movements >= 2 or (movements >= 1 and framing)):
        return False
    # Negative arms: equity accounts (headers joined — the
    # account names fragment across header cells — or stub
    # section lines), statement section lines, and the
    # purchases/sales pair of a fair-value walk.
    header_text = " ".join(normalize_text(header) for header in geometry.headers)
    if any(term in header_text for term in _EQUITY_ACCOUNT_TERMS):
        return False
    if any(term in stub for stub in stubs for term in _EQUITY_ACCOUNT_TERMS):
        return False
    if any(term in stub for stub in stubs for term in _STATEMENT_SECTION_TERMS):
        return False
    return not (
        any("purchases" in stub for stub in stubs)
        and any("sales" in stub for stub in stubs)
    )


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
        walk, subject = claim_shape(geometry)
        if not (walk and subject):
            return "aoci: no rollforward evidence"
    if "aoci_rollforward" in claims and "equity_statement" not in claims:
        walk, subject = claim_shape(geometry)
        if not (walk and subject):
            missing = "walk" if not walk else "subject"
            return f"aoci: claim shape missing {missing}"
    if "aoci_rollforward" in claims:
        _, subject = claim_shape(geometry)
        if not subject:
            return "aoci: claim shape missing subject"
    return None
