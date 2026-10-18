"""Table classification and section partitioning for Form 144 HTML filings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from edgar_sec.domain.forms.common.statutory import COMMON_STATUTORY_LEXICAL_PACK
from edgar_sec.engine.forms.common.entities import (
    EXCHANGE_RE,
    IRS_RE,
    STATE_ZIP_RE,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.signatures import is_signature_table
from edgar_sec.engine.forms.common.tables import (
    is_instruction_row,
    is_single_cell_empty_table,
    is_trailing_signature_table,
)
from edgar_sec.domain.forms.families.form144.evidence import (
    FORM144_BOX_1_2_LEXICAL_PACK,
    FORM144_BOX_3_LEXICAL_PACK,
    FORM144_HEADER_LEXICAL_PACK,
    FORM144_INSTRUCTION_VETO_PHRASES,
    FORM144_TABLE_I_LEXICAL_PACK,
    FORM144_TABLE_II_LEXICAL_PACK,
)
from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html
from edgar_sec.engine.forms.form144.patterns import (
    NUMERIC_TOKEN_RE,
    PHONE_RE,
    SEC_FILE_LABEL_RE,
)
from edgar_sec.engine.tables.ascii_html.converter import resolve_html_table_grid
from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.dates import (
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
    parse_date,
)
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)

_COMPILED_HEADER_PACK = compile_evidence_pack(FORM144_HEADER_LEXICAL_PACK)
_COMPILED_BOX_1_2_PACK = compile_evidence_pack(FORM144_BOX_1_2_LEXICAL_PACK)
_COMPILED_BOX_3_PACK = compile_evidence_pack(FORM144_BOX_3_LEXICAL_PACK)
_COMPILED_TABLE_I_PACK = compile_evidence_pack(FORM144_TABLE_I_LEXICAL_PACK)
_COMPILED_TABLE_II_PACK = compile_evidence_pack(FORM144_TABLE_II_LEXICAL_PACK)
_COMPILED_STATUTORY_PACK = compile_evidence_pack(COMMON_STATUTORY_LEXICAL_PACK)
_EVIDENCE_CTX = EvidenceContext(min_words=1)

_INSTRUCTION_VETO_RE = re.compile(
    build_alternation(FORM144_INSTRUCTION_VETO_PHRASES, auto_escape=True, compact=True)
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_NUMBERED_NOTE_RE = re.compile(r"^\d+[.)]?\s+[a-z]")


class SectionRole(StrEnum):
    HEADER = "header"
    COVER_BOX_1_2 = "cover_box_1_2"
    PROPOSED_SALE_BOX_3 = "proposed_sale_box_3"
    COMBINED_COVER = "combined_cover"
    INSTRUCTIONS = "instructions"
    TABLE_I = "table_i"
    TABLE_II = "table_ii"
    SIGNATURES = "signatures"
    REMARKS = "remarks"
    PAGE_ARTIFACT = "page_artifact"
    UNPARSED = "unparsed"


_DATA_ROLES = frozenset(
    {
        SectionRole.COMBINED_COVER,
        SectionRole.COVER_BOX_1_2,
        SectionRole.PROPOSED_SALE_BOX_3,
        SectionRole.TABLE_I,
        SectionRole.TABLE_II,
        SectionRole.SIGNATURES,
        SectionRole.REMARKS,
    }
)
_EMPTY_GRID = ResolvedGrid(
    rows=(), column_alignments=(), column_widths=(), confidence=0.0
)


@dataclass(frozen=True, slots=True)
class ClassifiedSection:
    role: SectionRole
    table_index: int
    raw_node: FastHtmlNode
    resolved_grid: ResolvedGrid


@dataclass(frozen=True, slots=True)
class Form144Sections:
    cover_box_1_2: ClassifiedSection | None
    proposed_sale_box_3: ClassifiedSection | None
    table_i: ClassifiedSection | None
    table_ii: ClassifiedSection | None
    signatures: list[ClassifiedSection]
    remarks: list[ClassifiedSection]
    unparsed: list[ClassifiedSection]


def _has_table_i_evidence(lower: str) -> bool:
    if "table i" in lower and (
        "securities to be sold" in lower or "date you acquired" in lower
    ):
        return True
    if "date you acquired" in lower and "nature of acquisition" in lower:
        return True
    if (
        "table i" not in lower
        and "acquired" not in lower
        and "acquisition" not in lower
    ):
        return False
    score = score_tokens(tokenize(lower), _COMPILED_TABLE_I_PACK, _EVIDENCE_CTX)
    return score.score >= 3


def _has_table_ii_evidence(lower: str) -> bool:
    if "table ii" in lower and ("securities sold" in lower or "past 3 months" in lower):
        return True
    if (
        "securities sold during the past" in lower
        or "securities sold past 3 months" in lower
    ):
        return True
    if "title of securities sold" in lower and "gross proceeds" in lower:
        return True
    if "table ii" not in lower and "securities sold" not in lower:
        return False
    score = score_tokens(tokenize(lower), _COMPILED_TABLE_II_PACK, _EVIDENCE_CTX)
    return score.score >= 3


def _has_instruction_evidence(lower: str) -> bool:
    if lower.startswith("instruction") or "instructions to form 144" in lower:
        return True
    if "instructions:" in lower and "table i" not in lower and "table ii" not in lower:
        return True
    return (
        bool(_INSTRUCTION_VETO_RE.search(lower))
        and "table i" not in lower
        and "table ii" not in lower
    )


def _is_instruction_block(lower: str) -> bool:
    return not (_has_box_3_values(lower) or _has_cover_value_evidence(lower)) and (
        _has_instruction_evidence(lower)
    )


def _has_cover_value_evidence(lower: str) -> bool:
    return any(
        pattern.search(lower)
        for pattern in (IRS_RE, SEC_FILE_LABEL_RE, PHONE_RE, STATE_ZIP_RE)
    )


def _has_box_3_values(lower: str) -> bool:
    return "to be sold" in lower and "market value" in lower and "$" in lower


def _classify_table(lower: str, past_tables: bool = False) -> SectionRole:
    if not lower or not _NON_ALNUM_RE.sub("", lower):
        return SectionRole.PAGE_ARTIFACT
    if _has_table_i_evidence(lower):
        return SectionRole.TABLE_I
    if _has_table_ii_evidence(lower):
        return SectionRole.TABLE_II
    if is_signature_table(
        lower,
        past_tables,
        extra_markers=("date of notice", "date of plan adoption"),
    ) and (
        "/s/" in lower
        or "signature of reporting person" in lower
        or ("date of notice" in lower and "(signature)" in lower)
    ):
        return SectionRole.SIGNATURES
    has_cover_marker = (
        "name of issuer" in lower
        or ("issuer" in lower and "person for whose account" in lower)
        or (
            "address of issuer" in lower
            and any(
                term in lower
                for term in ("zip code", "telephone no", "state", "city", "street")
            )
        )
    )
    has_box_3 = (
        ("3 (a)" in lower or "3(a)" in lower)
        and any(w in lower for w in ("class", "broker", "sold", "shares", "units"))
    ) or (
        "to be sold" in lower
        and any(w in lower for w in ("shares", "units", "market value", "approx"))
    )

    if has_cover_marker and has_box_3:
        return SectionRole.COMBINED_COVER
    if has_cover_marker:
        return SectionRole.COVER_BOX_1_2
    if has_box_3:
        return SectionRole.PROPOSED_SALE_BOX_3

    if _is_instruction_block(lower):
        return SectionRole.INSTRUCTIONS

    if is_signature_table(lower, past_tables):
        return SectionRole.SIGNATURES
    if lower.startswith("remarks:") or (past_tables and _is_numbered_note(lower)):
        return SectionRole.REMARKS
    if "securities and exchange commission" in lower and "washington, d.c." in lower:
        return SectionRole.HEADER
    if "notice of proposed sale" in lower or "form 144" in lower:
        return SectionRole.HEADER

    if "sec use only" in lower and "document sequence" in lower:
        return SectionRole.PAGE_ARTIFACT

    if any(
        k in lower
        for k in (
            "omb",
            "18 u.s.c",
            "criminal",
            "intentional",
            "paperwork reduction",
            "public reporting",
        )
    ):
        stat_score = score_tokens(
            tokenize(lower), _COMPILED_STATUTORY_PACK, _EVIDENCE_CTX
        )
        if stat_score.score >= 2:
            return SectionRole.PAGE_ARTIFACT
    return SectionRole.UNPARSED


def _is_numbered_note(lower: str) -> bool:
    if lower.startswith("("):
        end = lower.find(")")
        if end > 1 and lower[1:end].isdigit():
            return True
    return len(lower) >= 100 and _NUMBERED_NOTE_RE.match(lower) is not None


def _merge_sections(
    existing: ClassifiedSection, incoming: ClassifiedSection
) -> ClassifiedSection:
    return ClassifiedSection(
        role=existing.role,
        table_index=existing.table_index,
        raw_node=existing.raw_node,
        resolved_grid=ResolvedGrid(
            rows=existing.resolved_grid.rows + incoming.resolved_grid.rows,
            column_alignments=existing.resolved_grid.column_alignments,
            column_widths=existing.resolved_grid.column_widths,
            confidence=existing.resolved_grid.confidence,
        ),
    )


def _is_box3_data_row(row: tuple[str, ...]) -> bool:
    if len(row) < 5:
        return False
    row_text = " ".join(row).lower()
    has_market = (
        "nyse" in row_text
        or "nasdaq" in row_text
        or "otc" in row_text
        or "stock exchange" in row_text
        or bool(EXCHANGE_RE.search(row_text))
    )
    has_date = bool(
        parse_date(row_text)
        or NUMERIC_DATE_RE.search(row_text)
        or RE_FULL_DATE.search(row_text)
    )
    num_count = sum(bool(NUMERIC_TOKEN_RE.search(c)) for c in row if c.strip())
    return has_market and has_date and num_count >= 2


def _is_table_ii_continuation(
    candidate: ResolvedGrid, existing: ClassifiedSection
) -> bool:
    rows = [
        row
        for row in candidate.rows
        if any(c.strip() for c in row)
        and not (
            row[0].strip().lower().startswith("remarks")
            and not any(c.strip() for c in row[1:])
        )
    ]
    if not rows:
        return False
    if len(rows) == 1 and all(
        cell.strip().lower() in {"n/a", "none", "no reported"}
        for cell in rows[0]
        if cell.strip()
    ):
        return True
    first_row_text = " ".join(rows[0]).lower()
    if any(
        k in first_row_text for k in ("trade date", "date of sale", "sale date")
    ) and any(
        k in first_row_text
        for k in ("shares", "units", "amount", "price", "principal", "proceeds")
    ):
        return True
    header = next(
        (
            row
            for row in existing.resolved_grid.rows
            if "name and address of seller" in " ".join(row).lower()
            and "gross proceeds" in " ".join(row).lower()
        ),
        (),
    )
    width = len(header)
    if width < 5:
        return False
    if any(
        all(c.strip().lower() in {"none", "n/a", ""} for c in row[1:])
        for row in rows
        if len(row) >= 4
    ):
        return True
    rows = [row for row in rows if len(row) >= width]
    matching_rows = sum(
        1
        for row in rows
        if (parse_date(row[2]) or bool(NUMERIC_DATE_RE.search(row[2])))
        and any(c.isdigit() for c in row[3])
        and any(c.isdigit() for c in row[4])
    )
    return matching_rows >= 1 and matching_rows * 2 >= len(rows)


def _is_box3_continuation(candidate: ResolvedGrid, existing: ClassifiedSection) -> bool:
    rows = [row for row in candidate.rows if any(cell.strip() for cell in row)]
    text = " ".join(" ".join(row) for row in rows).lower()
    if all(marker in text for marker in ("outstanding", "approx", "exchange")) and any(
        any(NUMERIC_TOKEN_RE.search(cell) for cell in row)
        and any(parse_date(cell) for cell in row)
        and any(EXCHANGE_RE.search(cell) for cell in row)
        for row in rows
    ):
        return True
    header_text = " ".join(" ".join(row) for row in existing.resolved_grid.rows).lower()
    if not all(
        marker in header_text
        for marker in ("title of the class", "aggregate", "approx", "exchange")
    ):
        return False
    width = max((len(row) for row in existing.resolved_grid.rows), default=0)
    sec_use_only = any(
        "sec use only" in cell.lower()
        for row in existing.resolved_grid.rows
        for cell in row
    )
    return any(
        (len(row) == width or (sec_use_only and len(row) == width - 1))
        and sum(NUMERIC_TOKEN_RE.search(cell) is not None for cell in row) >= 2
        and any(parse_date(cell) for cell in row)
        and any(EXCHANGE_RE.search(cell) for cell in row)
        for row in rows
    )


def _has_instruction_container(table: FastHtmlNode) -> bool:
    parent = table.parent
    if parent is None or parent.tag != "div":
        return False
    if "instructions:" in " ".join(parent.text().lower().split()):
        return True
    return any(
        sibling.tag == "div"
        and "instructions:" in " ".join(sibling.text().lower().split())
        for sibling in parent.previous_sibling_blocks(limit=2)
    )


def _is_instruction_table(lower: str, tbl: FastHtmlNode | None = None) -> bool:
    if (
        "$" in lower
        or _has_cover_value_evidence(lower)
        or "/s/" in lower
        or "(signature)" in lower
        or any(
            k in lower
            for k in (
                "3(a)",
                "3 (a)",
                "1(a)",
                "1 (a)",
                "2(a)",
                "2 (a)",
                "table i",
                "table ii",
            )
        )
    ):
        return False
    if any(normalize_exchange_name(t) for t in lower.split()):
        return False
    if tbl is not None and _has_instruction_container(tbl):
        return True
    return is_instruction_row(lower)


def _has_box3_value_row(grid: ResolvedGrid) -> bool:
    for row in grid.rows:
        numeric_count = sum(NUMERIC_TOKEN_RE.search(cell) is not None for cell in row)
        has_date = any(parse_date(cell) for cell in row)
        has_exchange = any(EXCHANGE_RE.search(cell) for cell in row)
        if numeric_count >= 3 or (numeric_count >= 2 and (has_date or has_exchange)):
            return True
        if numeric_count >= 1 and has_date and has_exchange:
            return True
    return False


def partition_form144_tables(html_text: str) -> Form144Sections:
    """Extract and classify tables from Form 144 HTML text into canonical sections."""
    root = parse_html(html_text)
    tables = root.css("table")
    cover_box_1_2: ClassifiedSection | None = None
    proposed_sale_box_3: ClassifiedSection | None = None
    table_i: ClassifiedSection | None = None
    table_ii: ClassifiedSection | None = None
    signatures: list[ClassifiedSection] = []
    remarks: list[ClassifiedSection] = []
    unparsed: list[ClassifiedSection] = []

    for idx, tbl in enumerate(tables):
        raw_text = tbl.raw_node.text(separator=" ")
        lower = " ".join(raw_text.lower().split())
        past_tables = bool(
            table_i is not None
            or table_ii is not None
            or proposed_sale_box_3 is not None
        )
        pre_grid = resolve_html_table_grid(tbl)
        if (
            proposed_sale_box_3 is not None
            and pre_grid.rows
            and _is_box3_data_row(pre_grid.rows[0])
        ):
            proposed_sale_box_3 = _merge_sections(
                proposed_sale_box_3,
                ClassifiedSection(
                    role=SectionRole.PROPOSED_SALE_BOX_3,
                    table_index=idx,
                    raw_node=tbl,
                    resolved_grid=ResolvedGrid(
                        rows=(pre_grid.rows[0],),
                        column_alignments=(),
                        column_widths=(),
                        confidence=1.0,
                    ),
                ),
            )
            pre_grid = ResolvedGrid(
                rows=pre_grid.rows[1:],
                column_alignments=pre_grid.column_alignments,
                column_widths=pre_grid.column_widths,
                confidence=pre_grid.confidence,
            )
            if not pre_grid.rows:
                continue
            lower = " ".join(
                " ".join(" ".join(r) for r in pre_grid.rows).lower().split()
            )

        role = _classify_table(lower, past_tables=past_tables)
        box3_grid = pre_grid if role == SectionRole.PROPOSED_SALE_BOX_3 else None
        if _is_instruction_table(lower, tbl):
            if role == SectionRole.PROPOSED_SALE_BOX_3:
                if box3_grid is not None and not _has_box3_value_row(box3_grid):
                    role = SectionRole.INSTRUCTIONS
            elif role not in {
                SectionRole.TABLE_I,
                SectionRole.TABLE_II,
                SectionRole.PAGE_ARTIFACT,
                SectionRole.REMARKS,
                SectionRole.COVER_BOX_1_2,
                SectionRole.COMBINED_COVER,
                SectionRole.SIGNATURES,
            }:
                role = SectionRole.INSTRUCTIONS
        grid = (
            box3_grid
            if role == SectionRole.PROPOSED_SALE_BOX_3 and box3_grid is not None
            else pre_grid
            if role in _DATA_ROLES
            else _EMPTY_GRID
        )
        if role == SectionRole.UNPARSED:
            candidate_grid = pre_grid
            if table_ii is not None and (
                is_single_cell_empty_table(candidate_grid.rows)
                or _is_table_ii_continuation(candidate_grid, table_ii)
            ):
                role = SectionRole.TABLE_II
                grid = candidate_grid
            elif (
                signatures
                or any(
                    any(
                        m in tables[next_idx].text().lower()
                        for m in ("signature", "date of notice")
                    )
                    for next_idx in range(idx + 1, min(len(tables), idx + 3))
                )
            ) and is_trailing_signature_table(lower, len(candidate_grid.rows)):
                role = SectionRole.SIGNATURES
                grid = candidate_grid
            elif "date of notice" in lower and (
                "signature" in lower or "____" in lower
            ):
                role = SectionRole.SIGNATURES
                grid = candidate_grid
            elif proposed_sale_box_3 is not None and _is_box3_continuation(
                candidate_grid, proposed_sale_box_3
            ):
                role = SectionRole.PROPOSED_SALE_BOX_3
                grid = candidate_grid
            elif (
                cover_box_1_2 is not None
                and "address" in lower
                and "street" in lower
                and "zip code" in lower
                and "issuer" not in lower
                and STATE_ZIP_RE.search(lower)
            ):
                role = SectionRole.COVER_BOX_1_2
                grid = candidate_grid
        section = ClassifiedSection(
            role=role, table_index=idx, raw_node=tbl, resolved_grid=grid
        )

        if role == SectionRole.COMBINED_COVER:
            if cover_box_1_2 is None:
                cover_box_1_2 = section
            else:
                cover_box_1_2 = _merge_sections(cover_box_1_2, section)
            if proposed_sale_box_3 is None:
                proposed_sale_box_3 = section
        elif role == SectionRole.COVER_BOX_1_2:
            if cover_box_1_2 is None:
                cover_box_1_2 = section
            else:
                cover_box_1_2 = _merge_sections(cover_box_1_2, section)
        elif role == SectionRole.PROPOSED_SALE_BOX_3:
            if proposed_sale_box_3 is None:
                proposed_sale_box_3 = section
            else:
                proposed_sale_box_3 = _merge_sections(proposed_sale_box_3, section)
        elif role == SectionRole.TABLE_I:
            if table_i is None:
                table_i = section
        elif role == SectionRole.TABLE_II:
            remarks_row = next(
                (r for r in grid.rows if r[0].strip().lower().startswith("remarks")),
                None,
            )
            if remarks_row:
                t2_rows = tuple(
                    r
                    for r in grid.rows
                    if not r[0].strip().lower().startswith("remarks")
                )
                grid = ResolvedGrid(
                    rows=t2_rows,
                    column_alignments=grid.column_alignments,
                    column_widths=grid.column_widths,
                    confidence=grid.confidence,
                )
                section = ClassifiedSection(
                    role=role, table_index=idx, raw_node=tbl, resolved_grid=grid
                )
                rem_text = " ".join(c.strip() for c in remarks_row if c.strip())
                if len(rem_text) > len("remarks:"):
                    remarks.append(
                        ClassifiedSection(
                            role=SectionRole.REMARKS,
                            table_index=idx,
                            raw_node=tbl,
                            resolved_grid=ResolvedGrid(
                                rows=(remarks_row,),
                                column_alignments=(),
                                column_widths=(),
                                confidence=1.0,
                            ),
                        )
                    )
            if table_ii is None:
                table_ii = section
            else:
                table_ii = _merge_sections(table_ii, section)
        elif role == SectionRole.SIGNATURES:
            signatures.append(section)
        elif role == SectionRole.REMARKS:
            remarks.append(section)
        elif role == SectionRole.UNPARSED:
            unparsed.append(section)

    return Form144Sections(
        cover_box_1_2=cover_box_1_2,
        proposed_sale_box_3=proposed_sale_box_3,
        table_i=table_i,
        table_ii=table_ii,
        signatures=signatures,
        remarks=remarks,
        unparsed=unparsed,
    )


__all__ = [
    "ClassifiedSection",
    "Form144Sections",
    "SectionRole",
    "partition_form144_tables",
]
