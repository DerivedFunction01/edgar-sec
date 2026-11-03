"""Form 11-K review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_11k.taxonomy import FORM_11K_ITEMS
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.signatures.blocks import (
    extract_anchored_signature,
)
from edgar_sec.engine.forms.cover.registrant import (
    extract_commission_file_number,
    next_content_line,
    parse_registrant_identity,
    previous_content_line,
)
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.tables.protection.tags import find_table_spans
from edgar_sec.foundation.regex.builder import build_alternation

_REPORT_KEYS = ("report_annual", "report_transition")

_FILE_NUMBER_RE = re.compile(
    r"commission file (?:number|no\.?)[:\s]*([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)",
    re.IGNORECASE,
)
_FILE_CAPTION_RE = re.compile(r"commission file (?:number|no\.?)", re.IGNORECASE)
_PLAN_CAPTION_RE = re.compile(r"full title of the plan", re.IGNORECASE)
_ISSUER_CAPTION_RE = re.compile(
    r"name of issuer of the securities held pursuant to the plan", re.IGNORECASE
)
_FISCAL_YEAR_END_RE = re.compile(
    r"for the fiscal year ended\s+([A-Z][a-z]+ \d{1,2}, \d{4})", re.IGNORECASE
)
_STATEMENTS_RE = re.compile(
    r"statements of net assets available for benefits", re.IGNORECASE
)
_SIGNATURE_ANCHORS = ("has duly caused this", "have duly caused this")
_ADDRESS_HINT_ALT = build_alternation(
    ["street", "avenue", "road", "boulevard", "drive", "suite", r"p\.?o\.? box"],
    auto_escape=False,
)
_ADDRESS_HINT_RE = re.compile(rf"\b(?:{_ADDRESS_HINT_ALT})\b", re.IGNORECASE)


def _value_candidate(raw: str) -> str | None:
    candidate = raw.strip("() ")
    if len(candidate) < 3 or not any(ch.isalpha() for ch in candidate):
        return None
    if (candidate[0].isalpha() and candidate[0].islower()) or candidate.endswith(":"):
        return None
    return candidate


def _caption_value(lines: list[str], caption_re: re.Pattern[str]) -> str | None:
    for index, line in enumerate(lines[:60]):
        match = caption_re.search(line)
        if match is None:
            continue
        remainder = _value_candidate(line[match.end() :].strip(" \t:—-"))
        if remainder is not None:
            return remainder
        following: list[str] = []
        cursor = index
        for _ in range(4):
            nxt = next_content_line(lines, cursor)
            if nxt is None:
                break
            cursor, text = nxt
            following.append(text)
        previous = previous_content_line(lines, index)
        previous_text = previous[1] if previous is not None else None
        ordered = (
            [previous_text, *following]
            if line.strip().startswith("(")
            else [*following, previous_text]
        )
        for raw in ordered:
            if raw is None:
                continue
            candidate = _value_candidate(raw)
            if candidate is not None and not _ADDRESS_HINT_RE.search(candidate):
                return candidate
    return None


def _extract_issuer_name(lines: list[str]) -> str | None:
    raw = _caption_value(lines, _ISSUER_CAPTION_RE)
    if raw is None:
        return None
    name = parse_registrant_identity(raw).name
    return name if name is not None else raw


def analyze_form_11k_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single Form 11-K review case producing cover-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "11-K")
    rep = analyze_form_case(case_dir, record, form=resolved_form, family="11-K")
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
        text, family="11-K", taxonomy_items=FORM_11K_ITEMS
    )
    detected_items = [section.item_identifier for section in sequence.sections]
    year_match = _FISCAL_YEAR_END_RE.search(text)

    fields = {
        "commission_file_number": extract_commission_file_number(
            text,
            number_pattern=_FILE_NUMBER_RE,
            caption_pattern=_FILE_CAPTION_RE,
        ),
        "plan_title": _caption_value(lines, _PLAN_CAPTION_RE),
        "issuer_name": _extract_issuer_name(lines),
        "fiscal_year_end": year_match.group(1) if year_match else None,
        "detected_items": detected_items,
        "statements_present": bool(_STATEMENTS_RE.search(text)),
        "signature": extract_anchored_signature(text, _SIGNATURE_ANCHORS),
    }
    rep["form_11k"] = fields

    states = rep["checkmarks"].get("candidate_states", {})
    if find_table_spans(text) and any(key not in states for key in _REPORT_KEYS):
        reinfer_unmasked_checkmarks(text, rep, family="11-K")
        states = rep["checkmarks"].get("candidate_states", {})
    for key in _REPORT_KEYS:
        rep["checkmarks"][key] = states.get(key) == "checked"

    if not fields["commission_file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_commission_file_number",
                "no commission file number matched on the cover",
            )
        )
    if not fields["plan_title"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_plan_title",
                "no plan title resolved from the cover caption",
            )
        )
    if not fields["issuer_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_issuer_name",
                "no issuer name resolved from the cover caption",
            )
        )
    if not any(rep["checkmarks"][key] for key in _REPORT_KEYS):
        rep["anomalies"].append(
            anomaly_record(
                "no_report_type_checked",
                "neither the annual nor the transition report box resolved as checked",
            )
        )
    if not fields["signature"]["present"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_signature",
                "no signatory resolved from the signature block",
            )
        )
    return rep


def summarize_form_11k_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Form 11-K case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="11-K")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_11k", {})

    summary["form_11k_scorecard"] = {
        "commission_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("commission_file_number")
        ),
        "plan_title_count": sum(
            1 for r in case_reports if fields_of(r).get("plan_title")
        ),
        "issuer_name_count": sum(
            1 for r in case_reports if fields_of(r).get("issuer_name")
        ),
        "fiscal_year_end_count": sum(
            1 for r in case_reports if fields_of(r).get("fiscal_year_end")
        ),
        "report_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _REPORT_KEYS
        },
        "item_coverage": {
            definition.item: sum(
                1
                for r in case_reports
                if definition.item in fields_of(r).get("detected_items", [])
            )
            for definition in FORM_11K_ITEMS
        },
        "statements_present_count": sum(
            1 for r in case_reports if fields_of(r).get("statements_present")
        ),
        "signature_present_count": sum(
            1 for r in case_reports if fields_of(r).get("signature", {}).get("present")
        ),
        "signature_conformed_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("signature", {}).get("conformed")
        ),
    }
    return summary


analyze_case = analyze_form_11k_review_case
summarize_cases = summarize_form_11k_cases

__all__ = [
    "analyze_case",
    "analyze_form_11k_review_case",
    "summarize_cases",
    "summarize_form_11k_cases",
]
