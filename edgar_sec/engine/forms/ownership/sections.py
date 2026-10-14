"""Table classification and section partitioning for Form 4 HTML filings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.domain.forms.families.ownership.evidence import (
    FOOTNOTE_VETO_PHRASES,
    OWNERSHIP_FOOTNOTE_LEXICAL_PACK,
)
from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html
from edgar_sec.engine.tables.ascii_html.converter import convert_html_table
from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)

_COMPILED_FOOTNOTE_PACK = compile_evidence_pack(OWNERSHIP_FOOTNOTE_LEXICAL_PACK)
_EVIDENCE_CTX = EvidenceContext(min_words=1)


class SectionRole(StrEnum):
    HEADER = "header"
    BOXES_1_TO_7 = "boxes_1_to_7"
    TABLE_I = "table_i"
    TABLE_II = "table_ii"
    SIGNATURES = "signatures"
    FOOTNOTES = "footnotes"
    PAGE_ARTIFACT = "page_artifact"
    UNPARSED = "unparsed"


@dataclass(frozen=True, slots=True)
class ClassifiedSection:
    role: SectionRole
    table_index: int
    raw_node: FastHtmlNode
    resolved_grid: ResolvedGrid


@dataclass(frozen=True, slots=True)
class Form4Sections:
    boxes_1_to_7: ClassifiedSection | None
    table_i: ClassifiedSection | None
    table_ii: ClassifiedSection | None
    signatures: ClassifiedSection | None
    footnotes: list[ClassifiedSection]
    unparsed: list[ClassifiedSection]


def _classify_table_text(
    text: str, num_cols: int = 0, past_tables: bool = False
) -> SectionRole:
    lower = text.lower()
    if not lower.strip():
        return SectionRole.PAGE_ARTIFACT

    # Relative ordering: Boxes 1 to 7 and Header never appear after transaction tables
    if not past_tables:
        if "name and address of reporting person" in lower or (
            "issuer name" in lower and "trading symbol" in lower
        ):
            return SectionRole.BOXES_1_TO_7
        if "check this box if no longer" in lower or "omb approval" in lower:
            return SectionRole.HEADER

    if "non-derivative" in lower or (
        "title of security" in lower and "derivative" not in lower
    ):
        return SectionRole.TABLE_I
    if "derivative" in lower:
        return SectionRole.TABLE_II
    if "signature of reporting person" in lower or "intentional misstatements" in lower:
        return SectionRole.SIGNATURES

    # Footnote classification with relative ordering boost in trailing zone
    if num_cols < 4 and not any(veto in lower for veto in FOOTNOTE_VETO_PHRASES):
        fn_score = score_tokens(tokenize(lower), _COMPILED_FOOTNOTE_PACK, _EVIDENCE_CTX)
        if fn_score.classification == "matched" and not fn_score.exclusions:
            return SectionRole.FOOTNOTES
        # In the trailing zone after Table I/II, any block with footnote markers is footnotes
        if past_tables and any(
            m in lower for m in ("(1)", "(2)", "1.", "2.", "(a)", "*")
        ):
            return SectionRole.FOOTNOTES

    if len(lower.strip()) < 80 and (
        "form 4" in lower or "page " in lower or "(continued)" in lower
    ):
        return SectionRole.PAGE_ARTIFACT
    return SectionRole.UNPARSED


def partition_form4_tables(html_content: str | bytes) -> Form4Sections:
    """Partition Form 4 HTML tables into typed functional sections."""
    tree = parse_html(html_content)
    tables = tree.css("table")

    boxes: ClassifiedSection | None = None
    table_i: ClassifiedSection | None = None
    table_ii: ClassifiedSection | None = None
    signatures: ClassifiedSection | None = None
    footnotes: list[ClassifiedSection] = []
    unparsed: list[ClassifiedSection] = []

    pending_role: SectionRole | None = None

    for idx, table_node in enumerate(tables):
        result = convert_html_table(table_node, table_index=idx)
        grid = result.resolved_grid
        text = " ".join(" ".join(r) for r in grid.rows).strip()
        num_cols = (
            len(grid.column_widths)
            if grid.column_widths
            else (len(grid.rows[0]) if grid.rows else 0)
        )
        past_tables = table_i is not None or table_ii is not None
        role = _classify_table_text(text, num_cols=num_cols, past_tables=past_tables)

        # Connect standalone section banners (1-cell title rows) to following grid
        is_banner = (
            len(grid.rows) <= 1
            and (len(grid.rows[0]) <= 1 if grid.rows else False)
            and role in (SectionRole.TABLE_I, SectionRole.TABLE_II)
        )
        if is_banner:
            pending_role = role
            continue

        if pending_role and role == SectionRole.UNPARSED and len(grid.rows) > 1:
            role = pending_role
            pending_role = None
        else:
            pending_role = None

        section = ClassifiedSection(
            role=role,
            table_index=idx,
            raw_node=table_node,
            resolved_grid=grid,
        )

        if role == SectionRole.BOXES_1_TO_7 and boxes is None:
            boxes = section
        elif role == SectionRole.TABLE_I and table_i is None:
            table_i = section
        elif role == SectionRole.TABLE_II and table_ii is None:
            table_ii = section
        elif role == SectionRole.SIGNATURES and signatures is None:
            signatures = section
        elif role == SectionRole.FOOTNOTES:
            footnotes.append(section)
        elif role == SectionRole.UNPARSED:
            unparsed.append(section)

    return Form4Sections(
        boxes_1_to_7=boxes,
        table_i=table_i,
        table_ii=table_ii,
        signatures=signatures,
        footnotes=footnotes,
        unparsed=unparsed,
    )


__all__ = [
    "ClassifiedSection",
    "Form4Sections",
    "SectionRole",
    "partition_form4_tables",
]
