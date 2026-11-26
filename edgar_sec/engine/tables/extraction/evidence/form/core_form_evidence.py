"""Step 8 core-form evidence evaluator (TEST_CORE_FORM).
Ports the re-derived frozen definitions (sig_int / sig_fv / sig_seg)
from the Step 8 re-derivation pricing act over the packet surface
(grid, caption stack, prose_before), read through the frozen NORM.
"""

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.core_form_specs import (
    CORE_FORM_SPECS,
)
from edgar_sec.engine.tables.numeric_cells import STRICT_NUMERIC_CELL_RE
from edgar_sec.foundation.text.date_patterns import (
    MONTH_PATTERN,
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
    STRICT_MONTH_PATTERN,
    YEAR_TOKEN_PATTERN,
    YEAR_TOKEN_RE,
    YEAR_TOKEN_SEARCH_RE,
)
from edgar_sec.foundation.text.patterns import FLOAT_SCALE_ALT, RE_WHITESPACE

DASH_CELLS = {"—", "–", "-"}
LEVEL_RE = re.compile(r"level ([123])\b")
USEFUL_LIFE_RE = re.compile(r"useful li(?:fe|ves)")
NET_WORD_RE = re.compile(r"\bnet\b")
FOOTNOTE_TAIL_RE = re.compile(r"\(\d+\)$")
MARKER_ONLY_RE = re.compile(r"^(\([a-z0-9]{1,2}\))+$")
FULL_PAREN_RE = re.compile(r"^\(.*\)$")
UNITS_STUB_RE = re.compile(r"^\(.*(?:%s).*\)$" % FLOAT_SCALE_ALT)
TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)$")

DATE_RES = (
    NUMERIC_DATE_RE,
    YEAR_TOKEN_RE,
    re.compile(r"\b(?:%s)\s+\d{1,2}\b" % STRICT_MONTH_PATTERN),
    re.compile(r"\b\d{1,2}\s+(?:%s)\b" % STRICT_MONTH_PATTERN),
    re.compile(
        r"\b(?:%s)\s+(?:%s)\b" % (STRICT_MONTH_PATTERN, YEAR_TOKEN_PATTERN)
    ),
)
FULLDATE_RES = (
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
    re.compile(r"\b\d{1,2}\s+(?:%s)\s+(?:%s)\b" % (MONTH_PATTERN, YEAR_TOKEN_PATTERN)),
)
LETTER_RE = re.compile(r"[a-z]")


def norml(text):
    """The frozen NORM: whitespace collapse, strip, lowercase."""
    return RE_WHITESPACE.sub(" ", text or "").strip().lower()


def stub_base(text):
    """Strip trailing parenthetical groups, repeatedly."""
    s = norml(text)
    while True:
        m = TRAILING_PAREN_RE.search(s)
        if not m:
            return s
        s = s[: m.start()].strip()


class CoreFormText:
    """The packet text surface the core-form signals read."""

    def __init__(self, table_text, caption_stack=(), prose_before=""):
        self.table_text = table_text or ""
        self.caption_stack = list(caption_stack or [])
        self.prose_before = prose_before or ""
        self.table = norml(self.table_text)
        self.caption = norml(" ".join(self.caption_stack))
        self.prose = norml(self.prose_before)
        self.all = norml(
            self.table_text
            + " "
            + " ".join(self.caption_stack)
            + " "
            + self.prose_before
        )
        self.rows = [
            [c for c in line.split(" | ")] for line in self.table_text.split("\n")
        ]
        self.rows_nb = [
            [c for c in line.split(" | ")]
            for line in self.table_text.split("\n")
            if line.strip()
        ]
        self.stubs = [norml(r[0]) if r else "" for r in self.rows]

    @classmethod
    def from_packet(cls, packet):
        return cls(
            packet.get("table_text") or "",
            packet.get("caption_stack") or [],
            packet.get("prose_before") or "",
        )

    @classmethod
    def from_rows(cls, rows, caption_stack=(), prose_before=""):
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack, prose_before)


@dataclass(frozen=True)
class CoreFormVerdict:
    core_present: bool
    detail: str


def _numeric_row(row, dash=True):
    for c in row[1:]:
        cc = norml(c).replace(" ", "")
        if STRICT_NUMERIC_CELL_RE.match(cc) or (dash and cc in DASH_CELLS):
            return True
    return False


def _block_numeric(row):
    """Numeric for header-block purposes: bare-year cells do not count."""
    for c in row[1:]:
        cc = norml(c).replace(" ", "")
        if cc in DASH_CELLS:
            return True
        if STRICT_NUMERIC_CELL_RE.match(cc) and not YEAR_TOKEN_RE.match(cc):
            return True
    return False


def _fulldate_row(row):
    return any(p.search(norml(c)) for c in row[1:] for p in FULLDATE_RES)


def _name_like(cell):
    c = norml(cell)
    if not c or not LETTER_RE.search(c):
        return False
    if STRICT_NUMERIC_CELL_RE.match(c.replace(" ", "")):
        return False
    if any(r.search(c) for r in DATE_RES):
        return False
    if YEAR_TOKEN_SEARCH_RE.search(c) and len(c.split()) <= 5:
        return False
    if "million" in c or "thousand" in c or "billion" in c:
        return False
    if "months" in c:
        return False
    if "fiscal" in c:
        return False
    if "bps" in c:
        return False
    return True


# ---------------- intangibles (components A-G) ----------------


def _is_year_row(stub):
    return bool(
        YEAR_TOKEN_RE.match(stub)
        or NUMERIC_DATE_RE.search(stub)
        or "year ended" in stub
    )


def _eval_intangibles(t, spec):
    classes = set()
    for stub in t.stubs:
        for term in spec.lexicon:
            if term in stub:
                classes.add(term)
    nclass = len(classes)
    yearrows = sum(1 for s in t.stubs if _is_year_row(s))
    accum_stub = any("accumulated amortization" in s for s in t.stubs)
    balance_stub = any("balance" in s for s in t.stubs)
    comp = {}
    comp["A"] = nclass >= 2 and (
        "accumulated amortization" in t.table
        or "gross carrying" in t.table
        or "cost basis" in t.table
    )
    comp["B"] = (
        "gross carrying" in t.table
        and "accumulated amortization" in t.table
        and NET_WORD_RE.search(t.table) is not None
    )
    comp["C"] = yearrows >= 3 and "amortiz" in t.all
    comp["D"] = "goodwill" in t.all and (
        balance_stub
        or any("acquired goodwill" in s for s in t.stubs)
        or "carrying amount of goodwill" in t.prose
    )
    comp["E"] = nclass >= 1 and accum_stub
    comp["F"] = nclass >= 2 and USEFUL_LIFE_RE.search(t.table) is not None
    comp["G"] = (accum_stub and balance_stub) or (
        any("amortization of" in s for s in t.stubs) and balance_stub
    )
    letters = "".join(k for k in "ABCDEFG" if comp[k])
    core = bool(letters)
    detail = "core form: %s (nclass=%d yearrows=%d)" % (
        letters or "-",
        nclass,
        yearrows,
    )
    return CoreFormVerdict(core, detail)


# ---------------- fair_value (components A/B/C) ----------------


def _eval_fair_value(t, spec):
    levels = len(set(LEVEL_RE.findall(t.table)))
    a = levels >= 2
    beg_balance_stub = any(
        ("beginning" in s) or s.startswith("balance") for s in t.stubs
    )
    b = "level 3" in t.all and (
        beg_balance_stub or "unobservable" in t.all or "valuation technique" in t.all
    )
    # C: header block ends at the first numeric row (stubbed or not);
    # bare-year cells do not break it. Class stubs are name-like stubs
    # (no "level"/"fair value", not total-initial) on a numeric row or
    # whose next non-blank row is numeric.
    header = []
    for r in t.rows:
        if _block_numeric(r):
            break
        header.append(" ".join(r))
    hb_fv = "fair value" in norml(" ".join(header))

    def class_ok(s):
        return (
            _name_like(s)
            and "level" not in s
            and "fair value" not in s
            and not s.startswith("total")
        )

    def next_nb_numeric(i):
        for r in t.rows[i + 1 :]:
            if any(norml(c) for c in r):
                return _numeric_row(r)
        return False

    class_stubs = 0
    for i, r in enumerate(t.rows):
        if not r or not class_ok(norml(r[0])):
            continue
        if _numeric_row(r) or next_nb_numeric(i):
            class_stubs += 1
    c = (
        (hb_fv and class_stubs >= 3)
        or "net asset value" in t.all
        or (
            any("carrying" in s for s in t.stubs)
            and any("fair value" in s for s in t.stubs)
        )
        or any("total fair value" in s for s in t.stubs)
        or (
            any("fair value" in s and "beginning" in s for s in t.stubs)
            and any("fair value" in s and "end of" in s for s in t.stubs)
        )
    )
    letters = "".join(k for k, v in (("A", a), ("B", b), ("C", c)) if v)
    core = bool(letters)
    detail = "core form: %s (levels=%d)" % (letters or "-", levels)
    if letters == "C":
        detail += " c-only named gap"
    return CoreFormVerdict(core, detail)


# ---------------- segment_reporting (members / measures) ----------------


def _seg_col(t, spec):
    out = set()
    for r in t.rows_nb[:6]:
        for c in r[1:]:
            cc = norml(c)
            if not _name_like(cc):
                continue
            if FOOTNOTE_TAIL_RE.search(cc) or MARKER_ONLY_RE.match(cc):
                continue
            if FULL_PAREN_RE.match(cc):
                continue
            if stub_base(cc) in spec.col_stoplist:
                continue
            out.add(cc)
    return out


def _seg_stub_ok(s, spec):
    if not _name_like(s):
        return False
    if s.startswith("total"):
        return False
    if FOOTNOTE_TAIL_RE.search(s):
        return False
    if UNITS_STUB_RE.match(s):
        return False
    if stub_base(s) in spec.stub_stoplist:
        return False
    return True


def _seg_stubn(t, spec):
    first_num = None
    for i, r in enumerate(t.rows):
        if r and _numeric_row(r, dash=False):
            first_num = i
            break
    out = set()
    for i, r in enumerate(t.rows):
        if not r:
            continue
        ok = _numeric_row(r, dash=False) or (
            first_num is not None and i < first_num and _fulldate_row(r)
        )
        if ok:
            s = norml(r[0])
            if _seg_stub_ok(s, spec):
                out.add(s)
    return out


def _eval_segment(t, spec):
    col = len(_seg_col(t, spec))
    stubn = len(_seg_stubn(t, spec))
    members = max(col, stubn)
    nmeas = sum(
        1 for terms in spec.measure_groups.values() if any(x in t.table for x in terms)
    )
    core = members >= 2 and nmeas >= 1
    detail = "core form: %s (members=%d measures=%d col=%d stubn=%d)" % (
        "S" if core else "-",
        members,
        nmeas,
        col,
        stubn,
    )
    return CoreFormVerdict(core, detail)


_EVALUATORS = {
    "intangibles": _eval_intangibles,
    "fair_value": _eval_fair_value,
    "segment_reporting": _eval_segment,
}


def evaluate_core_form(text, spec):
    """Evaluate one family's core-form signal over a CoreFormText."""
    return _EVALUATORS[spec.family](text, spec)


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_core_form(table, spec):
    """Stage adapter: evaluate a declared core-form spec over a table."""
    gate_spec = CORE_FORM_SPECS.get(spec.family)
    if gate_spec is None:
        return CoreFormVerdict(False, "no core-form spec for family")
    text = CoreFormText.from_rows(
        table.context.rows,
        table.context.caption_stack,
        table.context.prose_before,
    )
    return evaluate_core_form(text, gate_spec)


def failing_core_form_outcome(form_tests, family, kind):
    """The stamped core-form outcome failing one family's gate.
    Returns the outcome when a stamped, evaluable outcome for the
    family did not pass; None otherwise — never fails the gate."""
    for outcome in form_tests:
        if outcome.family == family and outcome.kind == kind:
            if outcome.evaluable and not outcome.passed:
                return outcome
            return None
    return None
