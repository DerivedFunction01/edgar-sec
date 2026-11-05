"""Schedule 14A review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_14a.taxonomy import FORM_14A_ITEMS
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.row_extraction import scan_numeric_cells
from edgar_sec.engine.forms.cover.registrant import (
    parse_registrant_identity,
    previous_content_line,
)
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.tables.protection.tags import find_table_spans

_CLASSIFICATION_KEYS = (
    "classification_preliminary",
    "classification_confidential",
    "classification_definitive",
    "classification_definitive_additional",
    "classification_soliciting_material",
)
_FEE_KEYS = (
    "fee_not_required",
    "fee_paid_previously",
    "fee_computed_on_table",
)
_ALL_KEYS = (
    "filed_by_registrant",
    "filed_by_other_party",
    *_CLASSIFICATION_KEYS,
    *_FEE_KEYS,
)

_REGISTRANT_LABEL_RE = re.compile(
    r"(?:exact )?name of registrant as specified in its charter", re.IGNORECASE
)
_FILING_PARTY_LABEL_RE = re.compile(
    r"name of person\(s\) filing proxy statement", re.IGNORECASE
)
_PROPOSAL_HEADING_RE = re.compile(
    r"^\s*(?:proposal|item)\s+(?:no\.\s*)?(\d{1,2}|[a-z])\b", re.IGNORECASE
)
_COMP_TABLE_CAPTION_RE = re.compile(r"summary compensation table", re.IGNORECASE)
_COMP_TABLE_HEADER_RE = re.compile(r"name and principal position", re.IGNORECASE)
_CELL_SPLIT_RE = re.compile(r"\s{2,}")
_YEAR_CELL_RE = re.compile(r"(?:19|20)\d{2}")
_COMP_TABLE_WINDOW = 120
_MIN_COMP_NUMERIC_CELLS = 3


def _extract_caption_name(lines: list[str], label_re: re.Pattern[str]) -> str | None:
    for index, line in enumerate(lines[:60]):
        match = label_re.search(line)
        if match is None:
            continue
        prefix = line[: match.start()].strip(" ,-(")
        if len(prefix) >= 3:
            name = parse_registrant_identity(prefix).name
            if name is not None:
                return name
        cursor = index
        for _ in range(4):
            previous = previous_content_line(lines, cursor)
            if previous is None:
                break
            cursor, text = previous
            name = parse_registrant_identity(text).name
            if name is not None:
                return name
    return None


def _comp_row_cells(line: str) -> tuple[str, ...]:
    return tuple(cell for cell in _CELL_SPLIT_RE.split(line.strip()) if cell)


def _is_comp_data_row(line: str) -> bool:
    cells = _comp_row_cells(line)
    if len(cells) < 4:
        return False
    numeric = scan_numeric_cells(cells, currency=True)
    if len(numeric) < _MIN_COMP_NUMERIC_CELLS:
        return False
    if not any(any(ch.isdigit() for ch in raw) for _, raw in numeric):
        return False
    first = cells[0]
    if _YEAR_CELL_RE.fullmatch(first) or not any(ch.isalpha() for ch in first):
        return False
    return True


def _extract_comp_table(lines: list[str]) -> dict[str, Any]:
    for index, line in enumerate(lines):
        if not (
            _COMP_TABLE_CAPTION_RE.search(line) or _COMP_TABLE_HEADER_RE.search(line)
        ):
            continue
        rows = 0
        for row_line in lines[index + 1 : index + 1 + _COMP_TABLE_WINDOW]:
            if _is_comp_data_row(row_line):
                rows += 1
        if rows:
            return {"present": True, "row_count": rows}
    return {"present": False, "row_count": 0}


def analyze_form_14a_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single Schedule 14A review case producing cover and body diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "DEF 14A")
    rep = analyze_form_case(case_dir, record, form=resolved_form, family="14A")
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    lines = text.splitlines()

    sequence = detect_section_sequence(
        text, family="14A", taxonomy_items=FORM_14A_ITEMS
    )
    detected_items = [section.item_identifier for section in sequence.sections]
    item8_span: tuple[int, int] | None = None
    for section in sequence.sections:
        if section.item_identifier == "ITEM 8":
            end = section.end_line if section.end_line is not None else len(lines)
            item8_span = (section.start_line, min(end + 1, len(lines)))
            break
    comp_lines = lines[item8_span[0] : item8_span[1]] if item8_span else lines
    proposals = {
        match.group(1).lower()
        for line in lines
        if (match := _PROPOSAL_HEADING_RE.match(line)) is not None
    }

    fields = {
        "registrant_name": _extract_caption_name(lines, _REGISTRANT_LABEL_RE),
        "filing_party_name": _extract_caption_name(lines, _FILING_PARTY_LABEL_RE),
        "detected_items": detected_items,
        "proposal_count": len(proposals),
        "comp_table": _extract_comp_table(comp_lines),
    }
    rep["form_14a"] = fields

    states = rep["checkmarks"].get("candidate_states", {})
    if find_table_spans(text) and any(
        key not in states for key in (*_CLASSIFICATION_KEYS, *_FEE_KEYS)
    ):
        reinfer_unmasked_checkmarks(text, rep, family="14A", case_dir=case_dir)
        states = rep["checkmarks"].get("candidate_states", {})
    for key in _ALL_KEYS:
        rep["checkmarks"][key] = states.get(key) == "checked"

    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the cover caption",
            )
        )
    if not any(rep["checkmarks"][key] for key in _CLASSIFICATION_KEYS):
        rep["anomalies"].append(
            anomaly_record(
                "no_classification_checked",
                "none of the five filing-classification boxes resolved as checked",
            )
        )
    if not any(rep["checkmarks"][key] for key in _FEE_KEYS):
        rep["anomalies"].append(
            anomaly_record(
                "no_fee_box_checked",
                "none of the three fee-payment boxes resolved as checked",
            )
        )
    if item8_span is not None and not fields["comp_table"]["present"]:
        rep["anomalies"].append(
            anomaly_record(
                "comp_table_missing",
                "Item 8 section detected but no Summary Compensation Table rows extracted",
            )
        )
    return rep


def summarize_form_14a_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Schedule 14A case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="14A")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_14a", {})

    item_coverage = {
        definition.item: sum(
            1
            for r in case_reports
            if definition.item in fields_of(r).get("detected_items", [])
        )
        for definition in FORM_14A_ITEMS
    }
    summary["form_14a_scorecard"] = {
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "filing_party_name_count": sum(
            1 for r in case_reports if fields_of(r).get("filing_party_name")
        ),
        "classification_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _CLASSIFICATION_KEYS
        },
        "cases_with_any_classification": sum(
            1
            for r in case_reports
            if any(r.get("checkmarks", {}).get(key) for key in _CLASSIFICATION_KEYS)
        ),
        "fee_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _FEE_KEYS
        },
        "cases_with_any_fee_box": sum(
            1
            for r in case_reports
            if any(r.get("checkmarks", {}).get(key) for key in _FEE_KEYS)
        ),
        "item_coverage": item_coverage,
        "mean_items_per_case": round(
            sum(len(fields_of(r).get("detected_items", [])) for r in case_reports)
            / total,
            2,
        ),
        "comp_table_present_count": sum(
            1 for r in case_reports if fields_of(r).get("comp_table", {}).get("present")
        ),
        "comp_table_row_total": sum(
            fields_of(r).get("comp_table", {}).get("row_count", 0) for r in case_reports
        ),
        "proposal_total": sum(
            fields_of(r).get("proposal_count", 0) for r in case_reports
        ),
    }
    return summary


analyze_case = analyze_form_14a_review_case
summarize_cases = summarize_form_14a_cases

__all__ = [
    "analyze_case",
    "analyze_form_14a_review_case",
    "summarize_cases",
    "summarize_form_14a_cases",
]
