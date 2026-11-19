"""EPS evidence seat: the depth-3 detector cell.
A claim seats on the recall-solved union H1 screened by
the packet-derived primary-statement detector.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.eps_specs import (
    EPS_EVIDENCE_SPECS_BY_TEST_ID,
    EpsEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable


@dataclass(frozen=True, slots=True)
class EpsText:
    """One geometry's seat text: rows, caption, lead, tail.
    Rows are normalized as the priced parse normalizes:
    cells stripped, trailing empties dropped, empty rows out."""

    rows: tuple[tuple[str, ...], ...] = ()
    caption: str = ""
    lead: str = ""
    prose_after: str = ""

    @property
    def stub_low(self) -> tuple[str, ...]:
        """Every row's first cell, lowercased."""
        return tuple((row[0] if row else "").lower() for row in self.rows)

    @property
    def stub_text(self) -> str:
        """Every stub label as one text: the priced surface."""
        return " ".join(self.stub_low)

    @property
    def all_text(self) -> str:
        """Every cell of every row as one text, lowercased."""
        return " ".join(" ".join(row) for row in self.rows).lower()

    @property
    def header_text(self) -> str:
        """The first row joined, lowercased."""
        return " ".join(self.rows[0]).lower() if self.rows else ""

    @classmethod
    def from_table(cls, table: TypedTable) -> EpsText:
        """Seat text from a typed table's context."""
        rows = []
        for row in table.context.rows:
            cells = [str(cell).strip() for cell in row]
            while cells and cells[-1] == "":
                cells.pop()
            if any(cells):
                rows.append(tuple(cells))
        context = table.context
        return cls(
            rows=tuple(rows),
            caption=" ".join(context.caption_stack).lower(),
            lead=(context.prose_before or "").lower(),
            prose_after=(context.prose_after or "").lower(),
        )


_DASHES = {"-", "–", "—", ""}


def _cell_value(cell: str) -> tuple[float | None, bool]:
    """(value, is_dash) for a numeric-position cell, else
    (None, False). Percent cells are not values here."""
    s = (cell or "").strip()
    if s in _DASHES:
        return 0.0, True
    if "%" in s:
        return None, False
    t = s.replace("$", "").replace(",", "").replace(" ", "")
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    try:
        v = float(t)
    except ValueError:
        return None, False
    return (-v if neg else v), False


def _share_scale(v: float, floor: float) -> bool:
    """Share-scale at a floor: integral and at least floor."""
    return abs(v) >= floor and float(v).is_integer()


def _split_vals(rows: tuple[tuple[str, ...], ...]):
    """The priced header/data split and per-cell values:
    vals[r][c] = (value, is_dash) or None."""
    start = len(rows)
    for i, r in enumerate(rows):
        n_num = sum(
            1 for c in r[1:] if _cell_value(c)[0] is not None and not _cell_value(c)[1]
        )
        stub_v = _cell_value(r[0])[0] if r else None
        if n_num >= 2 or stub_v is not None:
            start = i
            break
    data = rows[start:]
    n_cols = max((len(r) for r in data), default=0)
    vals = []
    for r in data:
        row_vals = []
        for c in range(n_cols):
            cell = r[c] if c < len(r) else ""
            cv = _cell_value(cell) if c >= 1 else (None, False)
            row_vals.append(cv if cv[0] is not None else None)
        vals.append(row_vals)
    return data, vals, n_cols


def _additive(vals: list, n_rows: int, n_cols: int, floor: float) -> bool:
    """The spine's additive identity at a share-scale floor:
    one column's v_i + Σ mids = v_k within tolerance."""
    for c in range(1, n_cols):
        seq = [(ri, vals[ri][c][0]) for ri in range(n_rows) if vals[ri][c] is not None]
        for ii in range(len(seq)):
            vi = seq[ii][1]
            if not _share_scale(vi, floor) or vi <= 0:
                continue
            for kk in range(ii + 2, len(seq)):
                vk = seq[kk][1]
                if not _share_scale(vk, floor) or vk <= vi:
                    continue
                mids = [seq[j][1] for j in range(ii + 1, kk)]
                if any(m < 0 for m in mids):
                    continue
                tol = max(1.0, 0.001 * vk)
                if sum(mids) > 0 and abs(vi + sum(mids) - vk) <= tol:
                    return True
    return False


def _additive_generic(cols: list, floor: float, tol_fn, integral: bool) -> bool:
    """The depth-2 tolerant additive test over column
    sequences, with integrality on or dropped."""
    for seq in cols:
        for ii in range(len(seq)):
            vi = seq[ii][1]
            if vi <= 0 or abs(vi) < floor:
                continue
            if integral and not float(vi).is_integer():
                continue
            for kk in range(ii + 2, len(seq)):
                vk = seq[kk][1]
                if vk <= vi or abs(vk) < floor:
                    continue
                if integral and not float(vk).is_integer():
                    continue
                mids = [seq[j][1] for j in range(ii + 1, kk)]
                if any(m < 0 for m in mids):
                    continue
                if sum(mids) > 0 and abs(vi + sum(mids) - vk) <= tol_fn(vk):
                    return True
    return False


def _additive_signed(cols: list) -> bool:
    """The signed-walk arm: an additive identity at decimal
    scale whose mids carry at least one negative and one
    positive value — the treasury walk; repurchases subtract."""
    for seq in cols:
        for ii in range(len(seq)):
            vi = seq[ii][1]
            if vi <= 0 or abs(vi) < 10:
                continue
            for kk in range(ii + 2, len(seq)):
                vk = seq[kk][1]
                if vk <= 0 or abs(vk) < 10:
                    continue
                mids = [seq[j][1] for j in range(ii + 1, kk)]
                if not any(m < 0 for m in mids):
                    continue
                if not any(m > 0 for m in mids):
                    continue
                tol = max(0.15, 0.001 * vk)
                if abs(vi + sum(mids) - vk) <= tol:
                    return True
    return False


@dataclass(frozen=True, slots=True)
class EpsLegs:
    """The priced rule's leg readings over one geometry."""

    basic_diluted: bool
    lead_basicand: bool
    pair: bool
    es_add: bool
    v_eq: bool
    v_eqx: bool
    v_comb: bool
    v_mil10: bool
    v_sub: bool
    v_signed: bool
    v_frag: bool
    v_fragx: bool
    v_any: bool
    w_spine: bool
    w_equiv: bool
    w_incr: bool
    w_any: bool
    h1: bool
    anatomy_first_fraction: float | None
    det_walk3: bool
    det_title: bool
    det_foot60: bool
    det_change: bool
    det: bool

    @property
    def bd_arm(self) -> bool:
        """The denominator arm: bd under the spine or a variant."""
        return self.basic_diluted and (self.es_add or self.v_any or self.v_signed)

    @property
    def claim(self) -> bool:
        """The seat claim: the union H1, the detector silent."""
        return self.h1 and not self.det


def legs_for(text: EpsText, spec: EpsEvidenceSpec) -> EpsLegs:
    """Every leg of the priced rule over one geometry's text."""
    rows = text.rows
    data, vals, n_cols = _split_vals(rows)
    stub_data = [(r[0].lower() if r else "") for r in data]
    basic_diluted = "basic" in text.all_text and "diluted" in text.all_text
    lead_basicand = spec.lead_term in text.lead
    pair = basic_diluted and lead_basicand
    es_add = _additive(vals, len(data), n_cols, 10000)
    es_add1k = _additive(vals, len(data), n_cols, 1000)

    def denom(term: str, other: str | None = None) -> list[int]:
        out = []
        for ri, s in enumerate(stub_data):
            if (
                term in s
                and (other is None or other not in s)
                and any(t in s for t in ("shares", "units", "denominator", "weighted"))
            ):
                out.append(ri)
        return out

    def col_vals(ris: list[int], c: int) -> list[float]:
        return [
            vals[ri][c][0]
            for ri in ris
            if vals[ri][c] is not None and not vals[ri][c][1]
        ]

    def share_any(v: float) -> bool:
        return (abs(v) >= 10000 and float(v).is_integer()) or abs(v) >= 100

    def rows_share(ris: list[int]) -> bool:
        return any(
            share_any(v)
            for ri in ris
            for c in range(1, n_cols)
            for v in col_vals([ri], c)
        )

    v_eq = False
    b_rows, d_rows = denom("basic"), denom("diluted")
    for c in range(1, n_cols):
        bv, dv = col_vals(b_rows, c), col_vals(d_rows, c)
        if any(abs(b - d) <= 0.01 and b >= 100 for b in bv for d in dv):
            v_eq = True
    v_eqx = v_eq and not es_add
    surfaces_text = text.stub_text + " " + text.caption + " " + text.header_text
    combined = (
        "basic and diluted" in surfaces_text or "basic & diluted" in surfaces_text
    )
    any_share = any(
        share_any(vals[ri][c][0])
        for ri in range(len(data))
        for c in range(1, n_cols)
        if vals[ri][c] is not None and not vals[ri][c][1]
    )
    v_comb = bool(
        combined
        and any_share
        and not rows_share(denom("basic", "diluted"))
        and not rows_share(denom("diluted", "basic"))
    )
    cols = [
        [(ri, vals[ri][c][0]) for ri in range(len(data)) if vals[ri][c] is not None]
        for c in range(1, n_cols)
    ]
    v_mil10 = _additive_generic(cols, 10, lambda vk: max(0.15, 0.001 * vk), False)
    v_signed = _additive_signed(cols)
    v_sub = es_add1k and not es_add
    groups: list[list[float]] = []
    cur: list[float] | None = None
    for ri, r in enumerate(data):
        stub = (r[0] or "").strip() if r else ""
        nums = [vals[ri][c][0] for c in range(1, n_cols) if vals[ri][c] is not None]
        if stub or cur is None:
            cur = list(nums)
            groups.append(cur)
        else:
            cur.extend(nums)
    maxlen = max((len(g) for g in groups), default=0)
    g_cols = [
        [(gi, g[c]) for gi, g in enumerate(groups) if len(g) > c] for c in range(maxlen)
    ]
    v_frag = _additive_generic(g_cols, 10000, lambda vk: max(1.0, 0.001 * vk), True)
    v_fragx = v_frag and not es_add
    v_any = v_eqx or v_comb or v_mil10 or v_sub or v_fragx
    w_spine = (
        "weighted average" in text.stub_text and "diluted" in text.all_text and es_add
    )
    w_equiv = "share equivalents" in text.stub_text and es_add
    w_incr = "incremental shares" in text.stub_text and es_add
    w_any = w_spine or w_equiv or w_incr
    h1 = pair or (basic_diluted and (es_add or v_any or v_signed)) or w_any

    stubs = text.stub_low
    n = len(stubs)
    first = None
    for i, s in enumerate(stubs):
        if any(t in s for t in spec.anatomy_terms):
            first = i
            break
    frac = (first / n) if (first is not None and n) else None
    det_foot60 = bool(frac is not None and frac >= spec.foot_threshold / 100.0)
    det_walk3 = (
        sum(1 for s in stubs if any(t in s for t in spec.walk_terms))
        >= spec.walk_min_rows
    )
    det_title = any(t in text.caption for t in spec.title_terms)
    head2 = " ".join(" ".join(r) for r in rows[:2]).lower() + " " + text.caption
    det_change = any(t in head2 for t in spec.change_terms)
    det = det_walk3 or det_title or det_foot60 or det_change
    return EpsLegs(
        basic_diluted=basic_diluted,
        lead_basicand=lead_basicand,
        pair=pair,
        es_add=es_add,
        v_eq=v_eq,
        v_eqx=v_eqx,
        v_comb=v_comb,
        v_mil10=v_mil10,
        v_sub=v_sub,
        v_signed=v_signed,
        v_frag=v_frag,
        v_fragx=v_fragx,
        v_any=v_any,
        w_spine=w_spine,
        w_equiv=w_equiv,
        w_incr=w_incr,
        w_any=w_any,
        h1=h1,
        anatomy_first_fraction=frac,
        det_walk3=det_walk3,
        det_title=det_title,
        det_foot60=det_foot60,
        det_change=det_change,
        det=det,
    )


@dataclass(frozen=True, slots=True)
class EpsEvidence:
    """The seat verdict for one geometry under the seat's spec."""

    admitted: bool
    evaluable: bool
    legs: EpsLegs | None
    detail: str


def evaluate_eps(text: EpsText, spec: EpsEvidenceSpec) -> EpsEvidence:
    """The seat verdict over one geometry's seat text."""
    legs = legs_for(text, spec)
    if legs.claim:
        if legs.pair:
            return EpsEvidence(True, True, legs, "pair form, detector silent")
        if legs.bd_arm:
            return EpsEvidence(True, True, legs, "denominator form, detector silent")
        return EpsEvidence(True, True, legs, "bridge form, detector silent")
    if legs.h1:
        return EpsEvidence(False, True, legs, "detector screens the union form")
    return EpsEvidence(False, True, legs, "no seat leg")


def evaluate_form_test_eps(table: TypedTable, spec: FormTestSpec) -> EpsEvidence:
    """Stage adapter: evaluate the declared seat spec over a table."""
    gate_spec = EPS_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return EpsEvidence(False, False, None, "no seat spec for test")
    if not table.context.rows:
        return EpsEvidence(False, False, None, "no grid rows")
    return evaluate_eps(EpsText.from_table(table), gate_spec)


@dataclass(frozen=True, slots=True)
class EpsDetectorVerdict:
    """The detector verdict for one geometry: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: EpsLegs | None
    detail: str


def evaluate_eps_detector(text: EpsText, spec: EpsEvidenceSpec) -> EpsDetectorVerdict:
    """The seat's detector alone over one geometry's seat text."""
    legs = legs_for(text, spec)
    fired = tuple(
        name
        for name, on in (
            ("det_walk3", legs.det_walk3),
            ("det_title", legs.det_title),
            ("det_foot60", legs.det_foot60),
            ("det_change", legs.det_change),
        )
        if on
    )
    if fired:
        return EpsDetectorVerdict(
            True, True, legs, "detector fired: " + ", ".join(fired)
        )
    return EpsDetectorVerdict(False, True, legs, "detector silent")


def evaluate_form_test_eps_detector(
    table: TypedTable, spec: FormTestSpec
) -> EpsDetectorVerdict:
    """Stage adapter: evaluate the family's seat detector over a table."""
    gate_spec = EPS_EVIDENCE_SPECS.get(spec.family)
    if gate_spec is None:
        return EpsDetectorVerdict(False, False, None, "no seat spec for test")
    if not table.context.rows:
        return EpsDetectorVerdict(False, False, None, "no grid rows")
    return evaluate_eps_detector(EpsText.from_table(table), gate_spec)
