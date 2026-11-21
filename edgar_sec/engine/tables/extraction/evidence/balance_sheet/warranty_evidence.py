"""Warranty-evidence gate: the ASC 460 walk over one geometry.

Evaluates the gate parameters declared as registry data in
warranty_specs.WARRANTY_EVIDENCE_SPECS; a claim requires the
subject, the bookend pair in any filed form, one movement type.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.text.period_keys import (
    numeric_dates as _numeric_dates,
    period_keys as _period_keys,
    priced_years as _priced_years,
    starts_with_numeric_date as _starts_with_numeric_date,
    starts_with_period as _starts_with_period,
)
from edgar_sec.engine.tables.extraction.specs.families.warranty_specs import (
    WARRANTY_EVIDENCE_SPECS_BY_TEST_ID,
    WarrantyEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import MONTH_NAMES, YEAR_TOKEN_PATTERN

# The priced surface is the measurement packet's: prose and grid
# text each capped at 6000 chars, as the collect's packet() caps.
_TEXT_CAP = 6000

_MONTH_ALT = build_alternation(MONTH_NAMES, auto_escape=True)
_MONTH_WORD_RE = re.compile(rf"\b(?:{_MONTH_ALT})\b", re.IGNORECASE)
_SEC_DATE_RE = re.compile(
    rf"^(?:(?:{_MONTH_ALT}) \d{{1,2}}, (?:{YEAR_TOKEN_PATTERN})"
    rf"|\d{{1,2}}/\d{{1,2}}/\d{{2,4}}):?$"
)


def _period_keys_x(spec: WarrantyEvidenceSpec, line: str) -> set:
    """Period keys with abbreviated months counted as keys too."""
    keys = _period_keys(line)
    abbrev_re = re.compile(
        rf"\b(?:{build_alternation(spec.abbrev_months, auto_escape=True)})\b"
    )
    for month in abbrev_re.findall(line):
        keys.add(("am", month.lower()))
    return keys


@dataclass(frozen=True, slots=True)
class WarrantyText:
    """One geometry's gate text: caption, prose, grid lines."""

    caption: str = ""
    prose: str = ""
    lines: tuple[str, ...] = ()

    @classmethod
    def from_table(cls, table: TypedTable) -> WarrantyText:
        """Gate text from a typed table, on the priced surface."""
        context = table.context
        table_text = "\n".join(
            " | ".join(str(cell) for cell in row) for row in context.rows
        )
        return cls(
            caption=" ".join(context.caption_stack),
            prose=(context.prose_before or "")[-_TEXT_CAP:],
            lines=tuple(table_text[:_TEXT_CAP].split("\n")),
        )


@dataclass(frozen=True, slots=True)
class WarrantyEvidence:
    """The gate verdict for one geometry under the family's spec."""

    admitted: bool
    detail: str


_REFUSED_NO_SPEC = WarrantyEvidence(False, "no gate spec for test id")


def _f2_forms(
    spec: WarrantyEvidenceSpec, lines_l: list[str], first_line: str
) -> list[str]:
    """The F2 bookend forms: the pair in its phase-2 dialects."""
    begin_row = any("balance" in ln and "beginning" in ln for ln in lines_l)
    end_row = any(
        "balance" in ln and ("ending" in ln or "end of" in ln) for ln in lines_l
    )
    dated = [ln for ln in lines_l if "balance" in ln and _priced_years(ln)]
    years: set[str] = set()
    months: set[str] = set()
    for ln in dated:
        years.update(_priced_years(ln))
        months.update(name for name in MONTH_NAMES if name in ln)
    anchor_lines = [ln for ln in lines_l if any(a in ln for a in spec.anchors)]
    akeys: set = set()
    for ln in anchor_lines:
        akeys |= _period_keys(ln)
    bare = [ln for ln in lines_l if _starts_with_period(ln)]
    bkeys: set = set()
    for ln in bare:
        bkeys |= _period_keys(ln)
    horiz_keys = _period_keys(first_line)
    if "beginning" in first_line:
        horiz_keys.add("beginning")
    if " end" in first_line:
        horiz_keys.add("end")
    forms = []
    if begin_row and end_row:
        forms.append("word pair")
    if len(dated) >= 2 and (len(years) >= 2 or len(months) >= 2):
        forms.append("dated pair")
    if len(anchor_lines) >= 2 and len(akeys) >= 2:
        forms.append("anchor pair")
    if any("beginning" in ln for ln in anchor_lines) and any(
        "end of" in ln or "ending" in ln for ln in anchor_lines
    ):
        forms.append("anchor word")
    if len(bare) >= 2 and len(bkeys) >= 2:
        forms.append("bare pair")
    if any(a in first_line for a in spec.anchors) and len(horiz_keys) >= 2:
        forms.append("horizontal header")
    return forms


def _transposed(
    spec: WarrantyEvidenceSpec,
    lines_l: list[str],
    first_idx: int,
    subject_re: re.Pattern,
) -> bool:
    """The R3 arm: bookends as column headers, read on the grid."""
    if first_idx < 0:
        return False
    hcells = [cell.strip() for cell in lines_l[first_idx].split("|")]
    period_cols = [j for j in range(1, len(hcells)) if _period_keys_x(spec, hcells[j])]
    if len(period_cols) < 2:
        return False
    move_rows: list[int] = []
    balance_rows: list[tuple[int, list[str]]] = []
    for index, ln in enumerate(lines_l):
        if index == first_idx or not ln.strip():
            continue
        cells = [cell.strip() for cell in ln.split("|")]
        stub = cells[0] if cells else ""
        if any(any(term in stub for term in terms) for _name, terms in spec.move_types):
            move_rows.append(index)
        if any(a in stub for a in spec.anchors) or subject_re.search(stub):
            balance_rows.append((index, cells))
    for row_idx, cells in balance_rows:

        def cellat(j: int) -> str:
            return cells[j] if j < len(cells) else ""

        if (
            cellat(period_cols[0])
            and cellat(period_cols[-1])
            and any(m != row_idx for m in move_rows)
        ):
            return True
    return False


def _f_arms(
    spec: WarrantyEvidenceSpec,
    lines_l: list[str],
    first_line: str,
    first_idx: int,
    subject_re: re.Pattern,
) -> list[str]:
    """The priced bookend arms beyond F2, with the arms named."""
    arms = []
    begin_key = [
        i for i, ln in enumerate(lines_l) if "beginning" in ln and _period_keys(ln)
    ]
    end_key = [
        i
        for i, ln in enumerate(lines_l)
        if ("ending" in ln or "end of" in ln) and _period_keys(ln)
    ]
    if any(i != j for i in begin_key for j in end_key):
        arms.append("dated bare pair")
    if (
        any("beginning" in ln for ln in lines_l)
        and any("ending" in ln or "end of" in ln for ln in lines_l)
        and len(_period_keys(first_line)) >= 2
    ):
        arms.append("header-dated bare pair")
    asof_keys: set = set()
    for ln in lines_l:
        if "balance" in ln and ("as of" in ln or " at " in ln):
            asof_keys |= _period_keys_x(spec, ln)
    if len(asof_keys) >= 2:
        arms.append("as-of closings")
    balance_keys: set = set()
    for ln in lines_l:
        if "balance" in ln:
            balance_keys |= _period_keys(ln)
    if len(balance_keys) >= 2:
        arms.append("dated-balance union")
    abbrev_re = re.compile(
        rf"\b(?:{build_alternation(spec.abbrev_months, auto_escape=True)})\b"
    )
    ye_lines = 0
    ye_years: set[str] = set()
    for ln in lines_l:
        if (
            ((_MONTH_WORD_RE.search(ln) or abbrev_re.search(ln)) and _priced_years(ln))
            or "year-end" in ln
            or "year end" in ln
        ):
            ye_lines += 1
            ye_years.update(_priced_years(ln))
    if ye_lines >= 2 and len(ye_years) >= 2:
        arms.append("year-end closing")
    if _transposed(spec, lines_l, first_idx, subject_re):
        arms.append("transposed")
    return arms


_CLOSE_LEX = ("ending", "end of", "year-end", "year end")


def _f_amendment_arms(
    spec: WarrantyEvidenceSpec,
    lines_l: list[str],
    zone_idx: list[int],
) -> list[str]:
    """The depth-2 amendment arms: header-dated pair, as-of pair."""
    hdr_keys: set = set()
    for index in zone_idx:
        hdr_keys |= _period_keys_x(spec, lines_l[index])
    open_rows = [i for i, ln in enumerate(lines_l) if "beginning" in ln]
    close_rows = [i for i, ln in enumerate(lines_l) if any(c in ln for c in _CLOSE_LEX)]
    arms = []
    if any(i != j for i in open_rows for j in close_rows) and len(hdr_keys) >= 2:
        arms.append("header-dated pair")
    asof_lines = [ln for ln in lines_l if "balanc" in ln and "as of" in ln]
    akeys = set(hdr_keys)
    for ln in asof_lines:
        akeys |= _period_keys_x(spec, ln)
    if (
        len(asof_lines) >= 2
        and any("beginning" in ln for ln in asof_lines)
        and len(akeys) >= 2
    ):
        arms.append("as-of header pair")
    return arms


def _subject_stubs(
    lines_l: list[str],
    nonempty: list[int],
    first_idx: int,
    subject_re: re.Pattern,
) -> tuple[bool, list[str]]:
    """Subject-hit stubs: the stub-hit flag, the stub texts.
    The stub is the first non-empty cell among a hit line's
    first two cells; texts are subject-matching, collapsed."""
    stub_hit = False
    stub_texts: list[str] = []
    for index in nonempty:
        if index == first_idx:
            continue
        if subject_re.search(lines_l[index]) is None:
            continue
        stub = ""
        for cell in lines_l[index].split("|")[:2]:
            if cell.strip():
                stub = cell.strip()
                break
        stub = " ".join(stub.split())
        if subject_re.search(stub):
            stub_hit = True
            stub_texts.append(stub)
    return stub_hit, stub_texts


def _bare_pair_scoped(
    spec: WarrantyEvidenceSpec,
    lines_l: list[str],
    nonempty: list[int],
    stub_texts: list[str],
) -> bool:
    """The depth-3 disciplines on the bare-pair branch.
    Any one of: a repeated subject stub, body section-date
    lines, or the fragmented bookend header."""
    if stub_texts and max(Counter(stub_texts).values()) >= 2:
        return True
    sec_positions: list[int] = []
    sec_keys: set = set()
    for pos, index in enumerate(nonempty):
        content = " ".join(lines_l[index].strip(" |").split())
        if _SEC_DATE_RE.match(content):
            sec_positions.append(pos)
            sec_keys |= _period_keys(content)
    if (
        len(sec_positions) >= 2
        and len(sec_keys) >= 2
        and any(pos >= spec.header_zone_lines for pos in sec_positions)
    ):
        return True
    zone = [lines_l[i] for i in nonempty[: spec.frag_zone_lines]]
    return (
        any("beginning" in ln for ln in zone)
        and any("ending" in ln or "end of" in ln for ln in zone)
        and any("balance" in ln for ln in zone)
    )


def _movement_types(spec: WarrantyEvidenceSpec, lines_l: list[str]) -> set[str]:
    """Distinct movement types over the lines, widened vocabulary."""
    types = set()
    for name, terms in spec.move_types:
        if any(any(term in ln for term in terms) for ln in lines_l):
            types.add(name)
    for term, name in spec.extra_move_terms:
        if any(term in ln for ln in lines_l):
            types.add(name)
    return types


def evaluate_warranty_evidence(
    text: WarrantyText,
    spec: WarrantyEvidenceSpec,
) -> WarrantyEvidence:
    """Evaluate one geometry's text against the family's gate spec."""
    cap_l = text.caption.lower()
    prose_l = text.prose.lower()
    lines_l = [ln.lower() for ln in text.lines]
    nonempty = [i for i, ln in enumerate(lines_l) if ln.strip()]
    first_idx = nonempty[0] if nonempty else -1
    first_line = lines_l[first_idx] if first_idx >= 0 else ""
    subject_re = re.compile(spec.subject_pattern)
    lead = (
        subject_re.search(cap_l) is not None
        or subject_re.search(prose_l[-spec.prose_tail_chars :]) is not None
        or subject_re.search(first_line) is not None
    )
    forms = _f2_forms(spec, lines_l, first_line)
    table_subject = False
    bare_pair_subject = False
    if not lead:
        s_table = any(
            subject_re.search(lines_l[i]) is not None
            for i in nonempty
            if i != first_idx
        )
        table_subject = s_table and ("word pair" in forms or "dated pair" in forms)
        lead = table_subject
        if not lead:
            stub_hit, stub_texts = _subject_stubs(
                lines_l, nonempty, first_idx, subject_re
            )
            bare_pair_subject = (
                s_table
                and stub_hit
                and "bare pair" in forms
                and "word pair" not in forms
                and "dated pair" not in forms
                and _bare_pair_scoped(spec, lines_l, nonempty, stub_texts)
            )
            lead = bare_pair_subject
    if not lead:
        return WarrantyEvidence(False, "subject not anchored")
    arms = _f_arms(spec, lines_l, first_line, first_idx, subject_re)
    zone_idx = nonempty[: spec.header_zone_lines]
    arms += _f_amendment_arms(spec, lines_l, zone_idx)
    if not forms and not arms:
        return WarrantyEvidence(False, "no bookend pair in any filed form")
    types = _movement_types(spec, lines_l)
    if not types:
        return WarrantyEvidence(False, "no movement type")
    detail = (
        f"warranty walk: bookends {', '.join(forms + arms)}, "
        f"movements {', '.join(sorted(types))}"
    )
    if table_subject:
        detail += " (subject: table bookend form)"
    if bare_pair_subject:
        detail += " (subject: table bare-pair form)"
    return WarrantyEvidence(True, detail)


def evaluate_form_test_warranty(
    table: TypedTable, spec: FormTestSpec
) -> WarrantyEvidence:
    """Stage adapter: evaluate a declared gate spec over a table."""
    gate_spec = WARRANTY_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return _REFUSED_NO_SPEC
    return evaluate_warranty_evidence(WarrantyText.from_table(table), gate_spec)
