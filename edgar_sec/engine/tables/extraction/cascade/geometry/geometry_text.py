"""Geometry text evidence: channels, headings, and table building.

A geometry's text is carried by channel (caption, lead-in, note
heading, stubs, grid); built from a typed table's context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.leadin_segmentation import (
    lead_title_text,
    leadin_segment,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence import (
    LeaseSeparatorText,
    block_purity,
    column_mass_shares,
    period_purity,
    period_step_count,
    period_stub_present,
    stub_ladder_purity,
    transposed_period_axis,
    year_span_prod,
)
from edgar_sec.engine.tables.extraction.separators.summary_separator import (
    SummarySeparatorResult,
    evaluate_summary_separator,
)
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import lead_channel_text
from edgar_sec.engine.tables.toc.patterns import RE_NOTE_HEADING_CUE

_HEADING_NUMBERED = re.compile(r"^\d+\.\s+\S")


def heading_text(prose_before: str, prose_after: str, caption: str) -> str:
    """Heading lines framing a geometry: note headings and titles."""
    lines: list[str] = []
    for source in (prose_before or "", prose_after or ""):
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if RE_NOTE_HEADING_CUE.search(stripped) or _HEADING_NUMBERED.match(
                stripped
            ):
                if len(stripped) < 120:
                    lines.append(stripped)
            elif len(stripped) >= 8 and stripped == stripped.upper():
                if any(ch.isalpha() for ch in stripped):
                    lines.append(stripped)
    lines.append(caption or "")
    return normalize_text(" ".join(lines))


FRAGMENT_MAX_STUBS = 8


@dataclass(frozen=True, slots=True)
class GeometryText:
    """One geometry's text evidence, by channel, plus context."""

    caption: str = ""
    leadin: str = ""
    notehead: str = ""
    lead_title: str = ""
    lead: str = ""
    prose_after: str = ""
    prose_tail: str = ""
    stubs: tuple[str, ...] = ()
    closure_closed: bool | None = None
    note_title: str | None = None
    section_item: str | None = None
    form_tests: tuple[FormTestOutcome, ...] = ()
    summary_separator: SummarySeparatorResult | None = None
    grid_text: str = ""
    headers: tuple[str, ...] = ()
    in_toc_span: bool = False
    in_closing_span: bool = False
    closing_kind: str | None = None
    front_matter: bool = False
    note_seated: bool = False
    numeric_cells: int = 0
    data_rows: int = 0
    grid_rows: int = 0
    max_row_cells: int = 0
    index_named_share: float = 0.0
    page_ref_share: float = 0.0
    page_ref_only: bool = False
    exhibit_stub_share: float = 0.0
    pct_row_share: float = 0.0
    section_form: str | None = None
    section_part: str | None = None
    section_title: str | None = None
    table_index: int = 0
    note_number: int | None = None
    year_span: int = 0
    stub_ladder_purity: float = 0.0
    period_stub_present: bool | None = None
    transposed_period_axis: bool | None = None
    period_steps: int = 0
    period_purity: float = 0.0
    block_purity: float = 0.0
    lease_mass_share: float | None = None
    foreign_mass_share: float | None = None

    @property
    def stub_text(self) -> str:
        """The stub distribution as one normalized skeleton text."""
        return normalize_text(" ".join(self.stubs))

    @property
    def is_fragment(self) -> bool:
        """A fragment: few stubs and no caption of its own."""
        return len(self.stubs) <= FRAGMENT_MAX_STUBS and not self.caption.strip()


def geometry_text_from_table(table, *, evaluate_stage: bool = True) -> GeometryText:
    """Build channel text from a TypedTable (duck-typed context)."""
    context = table.context
    caption = " | ".join(list(context.caption_stack) + list(table.caption.titles))
    stubs = tuple(row.label for row in table.rows if row.label)
    note = context.note
    section = context.section
    grid_text = normalize_text(
        " ".join(cell for row in context.rows for cell in row if cell.strip())
    )
    consumed = table.caption.consumed_rows
    first_data = next(
        (i for i, row in enumerate(table.rows) if row.kind.name == "DATA"),
        len(table.rows),
    )
    zone = max(consumed + table.header_rows, consumed + first_data)
    headers = tuple(cell for row in context.rows[:zone] for cell in row if cell.strip())
    pct_rows = sum(1 for row in context.rows if any("%" in str(cell) for cell in row))
    pct_row_share = pct_rows / max(len(context.rows), 1)
    separator_text = LeaseSeparatorText.from_rows(
        context.rows, context.caption_stack, context.prose_before
    )
    return GeometryText(
        caption=caption,
        lead=lead_channel_text(caption, context.prose_before or ""),
        leadin=leadin_segment(context.prose_before or ""),
        notehead=heading_text(
            context.prose_before or "", context.prose_after or "", caption
        ),
        lead_title=lead_title_text(context.prose_before or ""),
        prose_after=context.prose_after or "",
        prose_tail=normalize_text(context.prose_before or "")[-300:],
        stubs=stubs,
        note_title=note.title if note else None,
        note_number=note.number if note else None,
        section_item=section.item if section else None,
        form_tests=evaluate_form_tests(table) if evaluate_stage else (),
        summary_separator=(
            evaluate_summary_separator(table) if evaluate_stage else None
        ),
        grid_text=grid_text,
        headers=headers,
        in_toc_span=context.in_toc_span,
        in_closing_span=context.in_closing_span,
        closing_kind=context.closing_kind,
        front_matter=context.front_matter,
        note_seated=note is not None,
        numeric_cells=context.numeric_cells,
        data_rows=context.data_rows,
        grid_rows=context.grid_rows,
        max_row_cells=context.max_row_cells,
        index_named_share=context.index_named_share,
        page_ref_share=context.page_ref_share,
        page_ref_only=context.page_ref_only,
        exhibit_stub_share=context.exhibit_stub_share,
        pct_row_share=pct_row_share,
        section_form=section.form if section else None,
        section_part=section.part if section else None,
        section_title=section.title if section else None,
        table_index=context.table_index,
        year_span=year_span_prod(separator_text),
        stub_ladder_purity=stub_ladder_purity(separator_text) or 0.0,
        period_stub_present=period_stub_present(separator_text),
        period_steps=period_step_count(separator_text),
        period_purity=period_purity(separator_text) or 0.0,
        block_purity=block_purity(separator_text) or 0.0,
        transposed_period_axis=transposed_period_axis(separator_text),
        lease_mass_share=(
            None
            if (shares := column_mass_shares(separator_text)) is None
            else shares[0]
        ),
        foreign_mass_share=None if shares is None else shares[1],
    )
