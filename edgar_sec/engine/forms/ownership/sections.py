"""Table classification and section partitioning for Section 16 ownership HTML filings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.domain.forms.common.statutory import (
    COMMON_STATUTORY_LEXICAL_PACK,
)
from edgar_sec.engine.forms.common.signatures import is_signature_table
from edgar_sec.domain.forms.families.ownership.evidence import (
    FOOTNOTE_VETO_PHRASES,
    OWNERSHIP_BOXES_LEXICAL_PACK,
    OWNERSHIP_FOOTNOTE_LEXICAL_PACK,
    OWNERSHIP_HEADER_LEXICAL_PACK,
    OWNERSHIP_TABLE_I_LEXICAL_PACK,
    OWNERSHIP_TABLE_II_LEXICAL_PACK,
)
from edgar_sec.engine.document.html.cleaner import normalize_font_qualified_glyphs
from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html
from edgar_sec.engine.forms.ownership.patterns import (
    OWNERSHIP_CONTINUATION_RE,
    OWNERSHIP_MASTHEAD_RE,
    OWNERSHIP_PAGE_MARKER_RE,
)
from edgar_sec.engine.tables.ascii_html.converter import resolve_html_table_grid
from edgar_sec.engine.tables.ascii_html.model import (
    NON_ALNUM_RE,
    HorizontalAlign,
    ResolvedGrid,
    merge_resolved_grids,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.dates import MONTH_RE, NUMERIC_DATE_RE
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)

_COMPILED_FOOTNOTE_PACK = compile_evidence_pack(OWNERSHIP_FOOTNOTE_LEXICAL_PACK)
_COMPILED_HEADER_PACK = compile_evidence_pack(OWNERSHIP_HEADER_LEXICAL_PACK)
_COMPILED_BOXES_PACK = compile_evidence_pack(OWNERSHIP_BOXES_LEXICAL_PACK)
_COMPILED_TABLE_I_PACK = compile_evidence_pack(OWNERSHIP_TABLE_I_LEXICAL_PACK)
_COMPILED_TABLE_II_PACK = compile_evidence_pack(OWNERSHIP_TABLE_II_LEXICAL_PACK)
_COMPILED_STATUTORY_PACK = compile_evidence_pack(COMMON_STATUTORY_LEXICAL_PACK)
_EVIDENCE_CTX = EvidenceContext(min_words=1)
_FOOTNOTE_VETO_RE = re.compile(
    build_alternation(FOOTNOTE_VETO_PHRASES, auto_escape=True, compact=True)
)
_SIGNATURE_CONTINUATION_PHRASES = ("/s/", "by:", "for:", "date")
_PRE_COLUMN_SPLIT_RE = re.compile(r"\s{2,}")


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
    raw_node: FastHtmlNode | None
    resolved_grid: ResolvedGrid


@dataclass(frozen=True, slots=True)
class OwnershipSections:
    boxes_1_to_7: ClassifiedSection | None
    table_i: ClassifiedSection | None
    table_ii: ClassifiedSection | None
    signatures: ClassifiedSection | None
    footnotes: list[ClassifiedSection]
    unparsed: list[ClassifiedSection]


def _is_header_table(lower: str) -> bool:
    if bool(OWNERSHIP_MASTHEAD_RE.search(lower)):
        return True
    if bool(OWNERSHIP_CONTINUATION_RE.search(lower)) and "ticker" in lower:
        return True
    score = score_tokens(tokenize(lower), _COMPILED_HEADER_PACK, _EVIDENCE_CTX)
    return score.score >= 2 and not score.exclusions


def _is_box_table(lower: str) -> bool:
    if "derivative" in lower and "non-derivative" not in lower:
        return False
    score = score_tokens(tokenize(lower), _COMPILED_BOXES_PACK, _EVIDENCE_CTX)
    return score.score >= 2 and not score.exclusions


def _is_table_i_table(lower: str, past_tables: bool) -> bool:
    score = score_tokens(tokenize(lower), _COMPILED_TABLE_I_PACK, _EVIDENCE_CTX)
    return score.score >= 2 and not score.exclusions


def _is_table_ii_table(lower: str) -> bool:
    score = score_tokens(tokenize(lower), _COMPILED_TABLE_II_PACK, _EVIDENCE_CTX)
    return score.score >= 2 and not score.exclusions


def _is_page_artifact_table(lower: str, num_cols: int) -> bool:
    score = score_tokens(tokenize(lower), _COMPILED_STATUTORY_PACK, _EVIDENCE_CTX)
    if score.score >= 2:
        return True
    if len(lower) < 80:
        if bool(OWNERSHIP_PAGE_MARKER_RE.search(lower)):
            return True
        if (
            num_cols < 3
            and bool(MONTH_RE.search(lower) or NUMERIC_DATE_RE.search(lower))
            and not any(
                k in lower
                for k in (
                    "table",
                    "name and address",
                    "issuer name",
                    "statement for",
                    "date of original",
                )
            )
        ):
            return True
    return False


def _is_footnote_table(lower: str, past_tables: bool, num_cols: int) -> bool:
    if "footnote description" in lower or "explanation of responses" in lower:
        return True
    if lower.startswith("*"):
        return True
    if past_tables and num_cols < 6:
        if (
            any(
                f"({i})" in lower or f"[{i}]" in lower or f"{i}." in lower
                for i in range(1, 20)
            )
            or "*" in lower
        ):
            return True
    if not _FOOTNOTE_VETO_RE.search(lower) and num_cols < 6:
        fn_score = score_tokens(tokenize(lower), _COMPILED_FOOTNOTE_PACK, _EVIDENCE_CTX)
        if fn_score.classification == "matched" and not fn_score.exclusions:
            return True
    return False


def _classify_table_text(
    text: str, num_cols: int = 0, past_tables: bool = False
) -> SectionRole:
    lower = " ".join(text.lower().split())
    if not lower or not NON_ALNUM_RE.sub("", lower):
        return SectionRole.PAGE_ARTIFACT

    if (num_cols < 6 or past_tables) and (
        "explanation of responses" in lower or "footnote description" in lower
    ):
        return SectionRole.FOOTNOTES
    if _is_table_ii_table(lower):
        return SectionRole.TABLE_II
    if (
        _is_table_i_table(lower, past_tables)
        and past_tables
        and not any(k in lower for k in ("name and address", "issuer name and"))
    ):
        return SectionRole.TABLE_I
    if _is_box_table(lower):
        return SectionRole.BOXES_1_TO_7
    if _is_header_table(lower):
        return SectionRole.HEADER
    if _is_table_i_table(lower, past_tables):
        return SectionRole.TABLE_I
    if is_signature_table(lower, past_tables):
        return SectionRole.SIGNATURES
    if _is_page_artifact_table(lower, num_cols):
        return SectionRole.PAGE_ARTIFACT
    if _is_footnote_table(lower, past_tables, num_cols):
        return SectionRole.FOOTNOTES
    return SectionRole.UNPARSED


def _find_table_i_split(rows: tuple[tuple[str, ...], ...]) -> int | None:
    for i in range(1, len(rows)):
        row_text = " ".join(rows[i]).lower()
        if "table ii" in row_text:
            continue
        if (
            "table i" in row_text
            and any(
                k in row_text
                for k in (
                    "non-derivative",
                    "non derivative",
                    "securities",
                    "acquired",
                    "beneficially owned",
                )
            )
        ) or (
            "title of security" in row_text
            and any(k in row_text for k in ("instr", "transaction", "amount"))
        ):
            return i
    return None


def _find_signature_split(rows: tuple[tuple[str, ...], ...]) -> int | None:
    for i in range(1, len(rows)):
        row_text = " ".join(rows[i]).lower()
        if "signature of reporting person" in row_text or (
            ("/s/" in row_text or "signature" in row_text)
            and ("date" in row_text or "attorney" in row_text)
            and len(row_text) < 150
        ):
            return i
    return None


def _merge_sections(
    existing: ClassifiedSection, incoming: ClassifiedSection
) -> ClassifiedSection:
    return ClassifiedSection(
        role=existing.role,
        table_index=existing.table_index,
        raw_node=existing.raw_node,
        resolved_grid=merge_resolved_grids(
            existing.resolved_grid, incoming.resolved_grid
        ),
    )


def _standalone_boxes_section(
    tree: FastHtmlNode, table_count: int
) -> ClassifiedSection | None:
    paragraphs = tree.css("p")
    rows: list[tuple[str]] = []
    first_p: FastHtmlNode | None = None
    for paragraph in paragraphs:
        if paragraph.find_parent("table") is not None:
            continue
        text = paragraph.text(separator=" ").strip()
        lower = text.lower()
        if any(
            marker in lower
            for marker in (
                "reporting person",
                "issuer name",
                "statement for",
                "relationship of reporting",
            )
        ):
            if first_p is None:
                first_p = paragraph
            rows.append((text,))
    if len(rows) >= 2 and first_p is not None:
        return ClassifiedSection(
            role=SectionRole.BOXES_1_TO_7,
            table_index=table_count + 1,
            raw_node=first_p,
            resolved_grid=ResolvedGrid(
                rows=tuple(rows),
                column_alignments=(HorizontalAlign.LEFT,),
                column_widths=(max(map(len, (r[0] for r in rows))),),
            ),
        )
    return None


def _standalone_signature_section(
    tree: FastHtmlNode, table_count: int
) -> ClassifiedSection | None:
    paragraphs = tree.css("p")
    for start, paragraph in enumerate(paragraphs):
        if paragraph.find_parent("table") is not None:
            continue
        text = paragraph.text(separator="\n").strip()
        normalized = " ".join(text.lower().split())
        if "signature of reporting person" not in normalized:
            continue
        rows = [(text,)]
        if start > 0 and paragraphs[start - 1].find_parent("table") is None:
            prev_txt = paragraphs[start - 1].text(separator="\n").strip()
            if any(p in prev_txt.lower() for p in ("/s/", "-s-", "by:", "for:")) or (
                len(prev_txt) < 80
                and not any(k in prev_txt.lower() for k in ("table", "form", "sec "))
            ):
                rows.insert(0, (prev_txt,))
        for continuation in paragraphs[start + 1 :]:
            if continuation.find_parent("table") is not None:
                break
            text = continuation.text(separator="\n").strip()
            if any(
                phrase in text.lower() for phrase in _SIGNATURE_CONTINUATION_PHRASES
            ):
                rows.append((text,))
            else:
                break
        return ClassifiedSection(
            role=SectionRole.SIGNATURES,
            table_index=table_count,
            raw_node=paragraph,
            resolved_grid=ResolvedGrid(
                rows=tuple(rows),
                column_alignments=(HorizontalAlign.LEFT,),
                column_widths=(max(map(len, (row[0] for row in rows))),),
            ),
        )
    return None


class OwnershipSectionAssembler:
    """Stateful assembler aggregating tables into typed ownership sections."""

    __slots__ = (
        "boxes",
        "table_i",
        "table_ii",
        "signatures",
        "footnotes",
        "unparsed",
        "pending_banner",
    )

    def __init__(self) -> None:
        self.boxes: ClassifiedSection | None = None
        self.table_i: ClassifiedSection | None = None
        self.table_ii: ClassifiedSection | None = None
        self.signatures: ClassifiedSection | None = None
        self.footnotes: list[ClassifiedSection] = []
        self.unparsed: list[ClassifiedSection] = []
        self.pending_banner: SectionRole | None = None

    @property
    def past_tables(self) -> bool:
        return self.table_i is not None or self.table_ii is not None

    def accumulate(self, idx: int, node: FastHtmlNode, grid: ResolvedGrid) -> None:
        text = " ".join(" ".join(r) for r in grid.rows).strip()
        num_cols = (
            len(grid.column_widths)
            if grid.column_widths
            else (len(grid.rows[0]) if grid.rows else 0)
        )
        role = _classify_table_text(
            text, num_cols=num_cols, past_tables=self.past_tables
        )

        t1_split = _find_table_i_split(grid.rows)
        if (
            t1_split is not None
            and 0 < t1_split < len(grid.rows)
            and (
                role in (SectionRole.BOXES_1_TO_7, SectionRole.HEADER)
                or _is_box_table(
                    " ".join(" ".join(r) for r in grid.rows[:t1_split]).lower()
                )
            )
        ):
            box_grid = ResolvedGrid(
                rows=grid.rows[:t1_split],
                column_alignments=grid.column_alignments,
                column_widths=grid.column_widths,
            )
            t1_grid = ResolvedGrid(
                rows=grid.rows[t1_split:],
                column_alignments=grid.column_alignments,
                column_widths=grid.column_widths,
            )
            self._append_section(
                ClassifiedSection(
                    role=SectionRole.BOXES_1_TO_7,
                    table_index=idx,
                    raw_node=node,
                    resolved_grid=box_grid,
                )
            )
            self._append_section(
                ClassifiedSection(
                    role=SectionRole.TABLE_I,
                    table_index=idx,
                    raw_node=node,
                    resolved_grid=t1_grid,
                )
            )
            return

        if role in (SectionRole.TABLE_I, SectionRole.TABLE_II):
            sig_split = _find_signature_split(grid.rows)
            if sig_split is not None and 0 < sig_split < len(grid.rows):
                main_grid = ResolvedGrid(
                    rows=grid.rows[:sig_split],
                    column_alignments=grid.column_alignments,
                    column_widths=grid.column_widths,
                )
                sig_grid = ResolvedGrid(
                    rows=grid.rows[sig_split:],
                    column_alignments=grid.column_alignments,
                    column_widths=grid.column_widths,
                )
                self._append_section(
                    ClassifiedSection(
                        role=role,
                        table_index=idx,
                        raw_node=node,
                        resolved_grid=main_grid,
                    )
                )
                self._append_section(
                    ClassifiedSection(
                        role=SectionRole.SIGNATURES,
                        table_index=idx,
                        raw_node=node,
                        resolved_grid=sig_grid,
                    )
                )
                return

        is_banner = (
            len(grid.rows) <= 1
            and (len(grid.rows[0]) <= 1 if grid.rows else False)
            and role in (SectionRole.TABLE_I, SectionRole.TABLE_II)
            and ("table i" in text.lower() or "table ii" in text.lower())
            and "amount of" not in text.lower()
        )
        if is_banner:
            self.pending_banner = role
            return

        if role == SectionRole.UNPARSED:
            if self.pending_banner:
                role = self.pending_banner
            elif (
                self.table_i is not None
                and self.table_ii is None
                and self.signatures is None
                and num_cols >= 6
            ):
                role = SectionRole.TABLE_I
            elif (
                self.signatures is not None and len(text) < 100 and len(grid.rows) <= 2
            ):
                role = SectionRole.SIGNATURES
        self.pending_banner = None

        section = ClassifiedSection(
            role=role, table_index=idx, raw_node=node, resolved_grid=grid
        )
        self._append_section(section)

    def _append_section(self, section: ClassifiedSection) -> None:
        if section.role == SectionRole.BOXES_1_TO_7:
            self.boxes = (
                section if self.boxes is None else _merge_sections(self.boxes, section)
            )
        elif section.role == SectionRole.TABLE_I:
            self.table_i = (
                section
                if self.table_i is None
                else _merge_sections(self.table_i, section)
            )
        elif section.role == SectionRole.TABLE_II:
            self.table_ii = (
                section
                if self.table_ii is None
                else _merge_sections(self.table_ii, section)
            )
        elif section.role == SectionRole.SIGNATURES:
            self.signatures = (
                section
                if self.signatures is None
                else _merge_sections(self.signatures, section)
            )
        elif section.role == SectionRole.FOOTNOTES:
            self.footnotes.append(section)
        elif section.role == SectionRole.UNPARSED:
            self.unparsed.append(section)

    def build(self, tree: FastHtmlNode, table_count: int) -> OwnershipSections:
        boxes = self.boxes
        if boxes is None:
            boxes = _standalone_boxes_section(tree, table_count)
        sigs = self.signatures
        if sigs is None:
            sigs = _standalone_signature_section(tree, table_count)
        return OwnershipSections(
            boxes_1_to_7=boxes,
            table_i=self.table_i,
            table_ii=self.table_ii,
            signatures=sigs,
            footnotes=self.footnotes,
            unparsed=self.unparsed,
        )


def partition_ownership_tables(html_content: str | bytes) -> OwnershipSections:
    """Partition Section 16 ownership HTML tables into typed functional sections."""
    text = (
        html_content.decode("utf-8", errors="replace")
        if isinstance(html_content, bytes)
        else html_content
    )
    tree = parse_html(normalize_font_qualified_glyphs(text))
    assembler = OwnershipSectionAssembler()
    table_nodes = tree.css("table")
    if not table_nodes and tree.css("pre"):
        for idx, pre_node in enumerate(tree.css("pre")):
            lines = [l for l in pre_node.text().splitlines() if l.strip()]
            rows = tuple(tuple(_PRE_COLUMN_SPLIT_RE.split(l.strip())) for l in lines)
            if not rows:
                continue
            num_cols = max(len(r) for r in rows)
            grid = ResolvedGrid(
                rows=rows,
                column_alignments=(HorizontalAlign.LEFT,) * num_cols,
                column_widths=(50,) * num_cols,
            )
            assembler.accumulate(idx, pre_node, grid)
        return assembler.build(tree, len(tree.css("pre")))

    for idx, table_node in enumerate(table_nodes):
        grid = resolve_html_table_grid(table_node, table_index=idx)
        assembler.accumulate(idx, table_node, grid)
    return assembler.build(tree, len(table_nodes))


__all__ = [
    "ClassifiedSection",
    "OwnershipSectionAssembler",
    "OwnershipSections",
    "SectionRole",
    "partition_ownership_tables",
]
