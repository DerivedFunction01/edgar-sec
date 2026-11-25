"""Lease separator evidence (TEST_LEASE_SEPARATOR): spanprod_le_2
refuses a lease claim whose stub+header span two or fewer distinct
years; subj_before400 one whose subject lead names a financing
liability; assign_sibling_seat runs at filing level, debt-anchored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
    norml,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TOTAL_ROW_RE
from edgar_sec.engine.tables.numeric_cells import NUMERIC_TOKEN_RE
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_specs import (
    LEASE_SEPARATOR_SPECS,
    LeaseSeparatorSpec,
)
from edgar_sec.foundation.text.date_patterns import (
    YEAR_TOKEN_PATTERN,
    YEAR_TOKEN_SEARCH_RE,
)

__all__ = [
    "LeaseSeparatorText",
    "LeaseSeparatorVerdict",
    "apply_lease_assignment",
    "apply_lease_stub_refusal",
    "column_mass_shares",
    "debt_seat_claimed",
    "evaluate_form_test_lease_separator",
    "evaluate_lease_separator",
    "fired_separator_outcome",
    "period_stub_present",
    "stub_ladder_purity",
    "stub_refusal_reason",
    "subject_fires",
    "subject_surface",
    "transposed_period_axis",
    "year_span_prod",
]

DEBT_LADDER_TEST_ID = "debt_maturity_year_ladder"
DEBT_ADMISSION_TEST_ID = "debt_maturity_j1_admission"
_SUBJECT_RES = {
    leg.leg_id: re.compile(leg.pattern)
    for spec in LEASE_SEPARATOR_SPECS.values()
    for leg in spec.legs
    if leg.kind == "subject"
}


class LeaseSeparatorText:
    """One table's surfaces as the separator reads them: grid rows
    (the pricing instrument's row hygiene), caption stack, and
    prose_before for the subject leg."""

    def __init__(self, table_text: str = "", caption_stack=(), prose_before=""):
        self.table_text = table_text or ""
        self.caption_stack = tuple(caption_stack or ())
        self.prose_before = prose_before or ""
        rows = []
        for ln in self.table_text.split("\n"):
            if not ln.strip():
                continue
            cells = [c.strip() for c in ln.split("|")]
            while cells and cells[-1] == "":
                cells.pop()
            if any(cells):
                rows.append(cells)
        self.rows = rows

    @classmethod
    def from_rows(cls, rows, caption_stack=(), prose_before="") -> "LeaseSeparatorText":
        """Surfaces from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack, prose_before)

    @classmethod
    def from_packet(cls, packet) -> "LeaseSeparatorText":
        """Surfaces from a census packet (priced population)."""
        return cls(
            packet.get("table_text") or "",
            packet.get("caption_stack") or (),
            packet.get("prose_before") or "",
        )


@dataclass(frozen=True)
class LeaseSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def year_span_prod(text: LeaseSeparatorText) -> int:
    """Distinct year tokens over stub + header (the priced surface)."""
    stubs = " ".join(r[0] for r in text.rows if r and r[0])
    header = " ".join(text.rows[0]) if text.rows else ""
    years = set(YEAR_TOKEN_SEARCH_RE.findall(stubs + " " + header))
    return len(years)


def stub_ladder_purity(text: LeaseSeparatorText) -> float | None:
    """Stub ladder purity: ladder cells over non-empty stub cells.

    A stub cell (rows[1:] first cells) is a ladder cell when it
    carries a year token, a thereafter row, or a total row.
    """
    stub_cells = [r[0] for r in text.rows[1:] if r and r[0].strip()]
    if not stub_cells:
        return None
    ladder = sum(
        1
        for cell in stub_cells
        if YEAR_TOKEN_SEARCH_RE.search(cell)
        or "thereafter" in norml(cell)
        or TOTAL_ROW_RE.match(cell)
    )
    return ladder / len(stub_cells)


def subject_surface(text: LeaseSeparatorText, tail: int) -> str:
    """The subject surface: caption stack + the prose_before tail,
    read through the frozen NORM (the priced subj_before form)."""
    prose = text.prose_before or ""
    if tail:
        prose = prose[-tail:]
    return norml(" ".join(text.caption_stack) + " " + prose)


def subject_fires(text: LeaseSeparatorText, leg) -> bool:
    """True when the leg's regex matches the subject surface."""
    return _SUBJECT_RES[leg.leg_id].search(subject_surface(text, leg.tail)) is not None


def evaluate_lease_separator(
    text: LeaseSeparatorText, spec: LeaseSeparatorSpec
) -> LeaseSeparatorVerdict:
    """Evaluate one grid against the family's priced legs."""
    if not text.rows:
        return LeaseSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    fired: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "span" and year_span_prod(text) <= leg.limit:
            fired.append(leg.leg_id)
        if leg.kind == "subject" and subject_fires(text, leg):
            fired.append(leg.leg_id)
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return LeaseSeparatorVerdict(True, True, tuple(fired), detail)
    return LeaseSeparatorVerdict(False, True, (), "separator clear")


# Priced by the column/stub attribution trace over 125 labeled
# specimens: a stub cell is a period label only when the cell IS
# the period — a cell merely containing a year is not.
PERIOD_STUB_RE = re.compile(
    r"^\s*(?:"
    r"(?:fiscal\s+)?(?:" + YEAR_TOKEN_PATTERN + r")"
    r"(?:\s+fiscal\s+year)?(?:\s*\(.*\))?(?:\s+and\s+thereafter)?"
    r"|(?:remainder|remaining)(?:\s+of)?(?:\s+\w+)*"
    r"|thereafter"
    r"|within\s+one\s+year"
    r"|one\s+to\s+two\s+years|two\s+to\s+three\s+years"
    r"|three\s+to\s+four\s+years|four\s+to\s+five\s+years"
    r"|after\s+(?:" + YEAR_TOKEN_PATTERN + r")"
    r"|years?\s+end(?:ing|ed)\b.*"
    r"|year\s+\d{1,2}"
    r"|[a-z]{3,9}\s+(?:"
    + YEAR_TOKEN_PATTERN
    + r")\s*-\s*[a-z]{3,9}\s+(?:"
    + YEAR_TOKEN_PATTERN
    + r")"
    r")\s*$",
    re.IGNORECASE,
)
LEASE_NAMED_RE = re.compile(r"lease|rent", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^\(?\$?\s*-?" + NUMERIC_TOKEN_RE.pattern + r"\s*\)?%?$")
DOMINANCE_LEASE_SHARE_MAX = 0.01
DOMINANCE_FOREIGN_SHARE_MIN = 0.5


def _stub_cells(text: LeaseSeparatorText) -> list[str]:
    """Stub cells under the purity read's convention."""
    return [r[0] for r in text.rows[1:] if r and r[0].strip()]


def period_stub_present(text: LeaseSeparatorText) -> bool:
    """True when any stub cell is an anchored period label."""
    return any(PERIOD_STUB_RE.match(cell.strip()) for cell in _stub_cells(text))


def transposed_period_axis(text: LeaseSeparatorText) -> bool:
    """True when the period axis runs across the header zone:
    a thereafter header over at least two distinct header years,
    over lease-named stubs (comparative-year columns excluded)."""
    zone = [cell for row in text.rows[:3] for cell in row[1:] if cell.strip()]
    if not any("thereafter" in norml(c) for c in zone):
        return False
    years = set(YEAR_TOKEN_SEARCH_RE.findall(" ".join(zone)))
    if len(years) < 2:
        return False
    return any(LEASE_NAMED_RE.search(cell) for cell in _stub_cells(text))


def _number_value(cell: str) -> float | None:
    """One grid cell's numeric value, or None when not numeric."""
    c = cell.strip().replace("$", "").replace(",", "").replace("%", "")
    if not c or not _NUMBER_RE.match(cell.strip()):
        return None
    negative = c.startswith("(") and c.endswith(")")
    try:
        value = float(c.strip("()"))
    except ValueError:
        return None
    return -value if negative else value


def column_mass_shares(text: LeaseSeparatorText) -> tuple[float, float] | None:
    """(lease-named, largest foreign) numeric mass shares over
    instrument-named columns; None when the grid is not an
    instrument-column grid (period columns, or one side absent)."""
    rows = text.rows
    data_start = next(
        (
            i
            for i, row in enumerate(rows)
            if sum(1 for c in row[1:] if _number_value(c) is not None) >= 2
        ),
        None,
    )
    if data_start is None or data_start == 0:
        return None
    ncols = max(len(r) for r in rows)
    headers = [
        " ".join(
            str(rows[i][j])
            for i in range(data_start)
            if j < len(rows[i]) and str(rows[i][j]).strip()
        )
        for j in range(ncols)
    ]
    lease_mass = foreign_mass = 0.0
    foreign_max = 0.0
    named = 0
    for j in range(1, ncols):
        header = headers[j].strip()
        if not header or header.lower() == "total":
            continue
        if YEAR_TOKEN_SEARCH_RE.search(header) and not LEASE_NAMED_RE.search(header):
            continue
        mass = sum(
            abs(v)
            for row in rows[data_start:]
            if j < len(row) and (v := _number_value(str(row[j]))) is not None
        )
        if mass <= 0:
            continue
        named += 1
        if LEASE_NAMED_RE.search(header):
            lease_mass += mass
        else:
            foreign_mass += mass
            foreign_max = max(foreign_max, mass)
    total = lease_mass + foreign_mass
    if not named or total <= 0 or lease_mass <= 0 or foreign_mass <= 0:
        return None
    return lease_mass / total, foreign_max / total


def stub_refusal_reason(
    period_present: bool | None,
    transposed: bool | None,
    shares: tuple[float, float] | None,
) -> str | None:
    """The refusal detail for one geometry's reads, or None.
    Clause A needs both reads present and negative — a geometry
    carrying no stub read (None) is never refused on it."""
    if period_present is False and transposed is False:
        return "lease refusal: no period stub or transposed period axis"
    if shares is not None:
        lease_share, foreign_share = shares
        if (
            lease_share < DOMINANCE_LEASE_SHARE_MAX
            and foreign_share > DOMINANCE_FOREIGN_SHARE_MIN
        ):
            return (
                "lease refusal: combined grid, lease column mass "
                f"share {lease_share:.3f}"
            )
    return None


def apply_lease_stub_refusal(geometries, results):
    """Final filing-level pass: a lease claim is refused on the
    stub-composition and combined-grid dominance reads stamped
    on the geometry; it only removes claims."""
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    family = "lease_maturity"
    refused: dict[int, str] = {}
    for i, result in enumerate(results):
        if family not in result.claims:
            continue
        geometry = geometries[i]
        shares = None
        if geometry.lease_mass_share is not None:
            shares = (geometry.lease_mass_share, geometry.foreign_mass_share)
        reason = stub_refusal_reason(
            geometry.period_stub_present, geometry.transposed_period_axis, shares
        )
        if reason is not None:
            refused[i] = reason
    if not refused:
        return list(results)
    out = []
    for i, result in enumerate(results):
        if i not in refused:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores.get(family)
        if score is not None:
            scores[family] = FamilyScore(
                score.family,
                score.total,
                score.by_channel,
                score.evidence + (ClaimEvidence("gate", refused[i], 0.0),),
            )
        out.append(
            CompetitionResult(
                claims=tuple(name for name in result.claims if name != family),
                contested=tuple(name for name in result.contested if name != family),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=result.groups,
            )
        )
    return out


def debt_seat_claimed(form_tests) -> bool:
    """The debt seat's claim on one geometry, from its stamped
    outcomes: the year ladder and the J1 admission both passed."""
    outcomes = {o.test_id: o.passed for o in form_tests}
    return (
        outcomes.get(DEBT_LADDER_TEST_ID) is True
        and outcomes.get(DEBT_ADMISSION_TEST_ID) is True
    )


def apply_lease_assignment(geometries, results):
    """Filing-level pass: a lease claim is refused when another
    family claims the same geometry, or when the debt seat has
    seated it (assign_sibling_seat); it only removes claims.
    """
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    family = "lease_maturity"
    refused: dict[int, str] = {}
    for i, result in enumerate(results):
        if family not in result.claims:
            continue
        others = [name for name in result.claims if name != family]
        if others:
            refused[i] = "lease assignment: geometry co-claimed"
        elif debt_seat_claimed(geometries[i].form_tests):
            refused[i] = "lease assignment: geometry seated to debt_maturity"
    if not refused:
        return list(results)
    out = []
    for i, result in enumerate(results):
        if i not in refused:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores.get(family)
        if score is not None:
            scores[family] = FamilyScore(
                score.family,
                score.total,
                score.by_channel,
                score.evidence + (ClaimEvidence("gate", refused[i], 0.0),),
            )
        out.append(
            CompetitionResult(
                claims=tuple(name for name in result.claims if name != family),
                contested=tuple(name for name in result.contested if name != family),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=result.groups,
            )
        )
    return out


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_lease_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = LEASE_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return LeaseSeparatorVerdict(False, False, (), "no separator spec for family")
    text = LeaseSeparatorText.from_rows(
        table.context.rows, table.context.caption_stack, table.context.prose_before
    )
    return evaluate_lease_separator(text, gate_spec)
