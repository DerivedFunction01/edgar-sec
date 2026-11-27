"""Pension combination separator evidence (TEST_PENSION_COMBINATION).

The combination separator over one table: the priced FULL
composition's claim-local legs — row bound, revenue stub,
stub-key host, and the offset-stub legs; no leg fires, admitted.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.foundation.text.patterns import RE_WHITESPACE
from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.pension.pension_combination_specs import (
    CC_HDR_VOCAB,
    CC_TOKEN_VOCAB,
    COMBINATION_CORE_TERMS,
    GUARANTEE_TOKENS,
    HOST_COMBINATION_VOCAB,
    PENSION_COMBINATION_SPEC,
    REVENUE_STUBS,
    PensionCombinationSpec,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    PensionRoutedText,
    header_keys,
    read_routed,
    stub_key,
)

_HEADER_LINES = 3


def _stub_index() -> TermIndex:
    """One substring index over the combination stub terms:
    core and revenue kinds. Phrase entries only — the
    combination matching is literal substring."""
    entries = [TermEntry(term, "core") for term in COMBINATION_CORE_TERMS]
    entries.extend(TermEntry(term, "revenue") for term in REVENUE_STUBS)
    return TermIndex(entries)


_STUB_INDEX = _stub_index()


def _stub_norm(text):
    """The priced stub normalization: case and whitespace only."""
    return RE_WHITESPACE.sub(" ", (text or "").strip().lower())


class PensionCombinationText:
    """The packet text surface the combination separator reads."""

    def __init__(self, table_text, caption_stack=()):
        self.table_text = table_text or ""
        self.caption_stack = list(caption_stack or [])

    @classmethod
    def from_packet(cls, packet):
        return cls(packet.get("table_text") or "", packet.get("caption_stack") or [])

    @classmethod
    def from_rows(cls, rows, caption_stack=()):
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack)


@dataclass(frozen=True, slots=True)
class PensionCombinationVerdict:
    """The separator's read: admitted unless a priced leg kills."""

    admitted: bool
    detail: str


@dataclass(frozen=True, slots=True)
class _Read:
    n_rows: int
    census_n_rows: int
    census_n_cols: int
    core_present: bool
    revenue_stub: bool
    stub_keys: frozenset
    offset_tokens: frozenset
    hdr_keys: frozenset
    offset_stubs: tuple


def _read(text: PensionCombinationText) -> _Read:
    raw_lines = text.table_text.split("\n")
    census_lines = [ln for ln in raw_lines if ln.strip()]
    offset_rows = []
    for line in raw_lines:
        cells = [_stub_norm(c) for c in line.split("|")]
        cells = [c for c in cells if c]
        if cells:
            offset_rows.append(cells)
    offset_stubs = tuple(r[0] for r in offset_rows)
    stub_keys = set()
    for line in census_lines:
        cells = line.split("|")
        stub = cells[0].strip() if cells else ""
        if stub:
            keyed = stub_key(stub)
            if len(keyed) >= 3:
                stub_keys.add(keyed)
    headers = []
    for line in census_lines[:_HEADER_LINES]:
        headers.extend(c for c in (cell.strip() for cell in line.split("|")) if c)
    offset_tokens = set()
    for stub in offset_stubs:
        offset_tokens.update(stub_key(stub).split())
    stub_kinds: set[str] = set()
    for stub in offset_stubs:
        stub_kinds.update(_STUB_INDEX.scan(stub))
    return _Read(
        n_rows=len(offset_rows),
        census_n_rows=len(census_lines),
        census_n_cols=max((len(ln.split("|")) for ln in census_lines), default=0),
        core_present="core" in stub_kinds,
        revenue_stub="revenue" in stub_kinds,
        stub_keys=frozenset(stub_keys),
        offset_tokens=frozenset(offset_tokens),
        hdr_keys=header_keys(tuple(headers)),
        offset_stubs=offset_stubs,
    )


def _host_family(stub_keys) -> str | None:
    for family in sorted(HOST_COMBINATION_VOCAB):
        if stub_keys & HOST_COMBINATION_VOCAB[family]:
            return family
    return None


def evaluate_pension_combination(
    text: PensionCombinationText,
    spec: PensionCombinationSpec = PENSION_COMBINATION_SPEC,
) -> PensionCombinationVerdict:
    """Evaluate the combination separator over one table's text."""
    read = _read(text)
    if read.n_rows <= spec.rows_max:
        return PensionCombinationVerdict(False, "rows_le_2")
    if read.core_present:
        return PensionCombinationVerdict(True, "clear")
    if read.revenue_stub:
        return PensionCombinationVerdict(False, "revenue_stub")
    host = _host_family(read.stub_keys)
    if host is not None:
        # The host leg yields to the same benefit-payments read
        # as the routed separator's host leg: benefit terms on a
        # stub year ladder are the estimated-benefit-payments form.
        routed = read_routed(PensionRoutedText(text.table_text, text.caption_stack))
        if not (routed.benefit_terms and routed.stub_year_ladder):
            return PensionCombinationVerdict(False, f"host_stubkey (host {host})")
    if not read.stub_keys:
        guarantee = bool(read.offset_tokens & GUARANTEE_TOKENS)
        if guarantee:
            return PensionCombinationVerdict(False, "guarantee_offset")
        if (
            read.offset_stubs
            and (guarantee or read.offset_tokens & CC_TOKEN_VOCAB)
            and read.census_n_rows >= spec.real_table_min_rows
            and read.census_n_cols >= spec.real_table_min_cols
        ):
            return PensionCombinationVerdict(False, "offset_candidate")
    if len(read.hdr_keys & CC_HDR_VOCAB) >= spec.hdr_min_hits:
        return PensionCombinationVerdict(False, "cc_hdr_ge2")
    return PensionCombinationVerdict(True, "clear")


# ---------------- production wiring (stage adapter) ----------------


def evaluate_form_test_pension_combination(table, spec):
    """Stage adapter: evaluate the combination separator over a table."""
    text = PensionCombinationText.from_rows(
        table.context.rows, table.context.caption_stack
    )
    return evaluate_pension_combination(text)
