"""Form 15 review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.entities import COMMISSION_FILE_TOKEN_RE
from edgar_sec.engine.forms.common.signatures.blocks import extract_signature_block
from edgar_sec.engine.forms.cover.registrant import (
    next_content_line,
    parse_registrant_identity,
    previous_content_line,
)

_RULE_KEYS = (
    "rule_12g4_a1",
    "rule_12g4_a2",
    "rule_12h3_b1_i",
    "rule_12h3_b1_ii",
    "rule_15d6",
)

_FILE_NUMBER_RE = re.compile(
    r"commission file (?:numbers?|no\.?)[:\s]*([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)",
    re.IGNORECASE,
)
_FILE_CAPTION_RE = re.compile(r"commission file (?:numbers?|no\.?)", re.IGNORECASE)
_REGISTRANT_LABEL_RE = re.compile(r"exact name of registrant", re.IGNORECASE)
_HOLDERS_RE = re.compile(r"holders of record", re.IGNORECASE)
_HOLDER_WORDS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
)
_HOLDER_VALUE_RE = re.compile(
    rf":\s*(none|[0-9][0-9,]*|{'|'.join(_HOLDER_WORDS)})\b", re.IGNORECASE
)
_HOLDER_NUMBER_RE = re.compile(r"\b([0-9][0-9,]*)\b")
_HOLDER_NONE_RE = re.compile(r"\bnone\b", re.IGNORECASE)
_SIGNATURE_ANCHOR = "has caused this"
_HOLDER_WINDOW = 220


def _extract_file_number(text: str) -> str | None:
    match = _FILE_NUMBER_RE.search(text)
    if match is not None:
        return match.group(1)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not _FILE_CAPTION_RE.search(line):
            continue
        for neighbor in (
            previous_content_line(lines, index),
            next_content_line(lines, index),
        ):
            if neighbor is None:
                continue
            for token in neighbor[1].split():
                if COMMISSION_FILE_TOKEN_RE.fullmatch(token.strip(",;")):
                    return token.strip(",;")
    return None


def _extract_registrant_name(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        match = _REGISTRANT_LABEL_RE.search(line)
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


def _extract_holder_value(text: str) -> str | None:
    match = _HOLDERS_RE.search(text)
    if match is None:
        return None
    window = text[match.end() : match.end() + _HOLDER_WINDOW]
    valued = _HOLDER_VALUE_RE.search(window)
    if valued is not None:
        return valued.group(1).lower()
    if _HOLDER_NONE_RE.search(window):
        return "none"
    numbered = _HOLDER_NUMBER_RE.search(window)
    return numbered.group(1) if numbered is not None else None


def _extract_signature(text: str) -> dict[str, Any]:
    anchor = text.lower().find(_SIGNATURE_ANCHOR)
    tail = text[anchor:] if anchor >= 0 else "\n".join(text.splitlines()[-25:])
    block = extract_signature_block(tail)
    if block is None:
        return {"present": False, "conformed": False, "name": None}
    name = block.signatories[0].name if block.signatories else None
    return {
        "present": name is not None,
        "conformed": bool(block.is_conformed),
        "name": name,
    }


def _anomaly(kind: str, details: str) -> dict[str, Any]:
    return {"kind": kind, "details": details, "detail": details}


def analyze_form_15_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single Form 15 review case producing cover-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "15")
    rep = analyze_form_case(case_dir, record, form=resolved_form, family="15")
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    lines = text.splitlines()
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""

    fields = {
        "commission_file_number": _extract_file_number(cover_text)
        or _extract_file_number(text),
        "registrant_name": _extract_registrant_name(lines),
        "holder_value": _extract_holder_value(text),
        "signature": _extract_signature(text),
    }
    rep["form_15"] = fields

    states = rep["checkmarks"].get("candidate_states", {})
    for key in _RULE_KEYS:
        rep["checkmarks"][key] = states.get(key) == "checked"

    if not fields["commission_file_number"]:
        rep["anomalies"].append(
            _anomaly(
                "missing_commission_file_number",
                "no commission file number matched on the cover",
            )
        )
    if not fields["registrant_name"]:
        rep["anomalies"].append(
            _anomaly(
                "missing_registrant_name",
                "no registrant name resolved from the cover caption",
            )
        )
    if fields["holder_value"] is None:
        rep["anomalies"].append(
            _anomaly(
                "missing_holder_count",
                "no holder-of-record value matched after the caption",
            )
        )
    if not fields["signature"]["present"]:
        rep["anomalies"].append(
            _anomaly(
                "missing_signature",
                "no signatory resolved from the signature block",
            )
        )
    if not any(rep["checkmarks"][key] for key in _RULE_KEYS):
        rep["anomalies"].append(
            _anomaly(
                "no_rule_provision_checked",
                "none of the five rule provisions resolved as checked",
            )
        )
    return rep


def summarize_form_15_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Form 15 case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="15")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_15", {})

    summary["form_15_scorecard"] = {
        "commission_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("commission_file_number")
        ),
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "holder_value_count": sum(
            1 for r in case_reports if fields_of(r).get("holder_value") is not None
        ),
        "holder_none_count": sum(
            1 for r in case_reports if fields_of(r).get("holder_value") == "none"
        ),
        "signature_present_count": sum(
            1 for r in case_reports if fields_of(r).get("signature", {}).get("present")
        ),
        "signature_conformed_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("signature", {}).get("conformed")
        ),
        "rule_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _RULE_KEYS
        },
        "cases_with_any_rule": sum(
            1
            for r in case_reports
            if any(r.get("checkmarks", {}).get(key) for key in _RULE_KEYS)
        ),
    }
    return summary


analyze_case = analyze_form_15_review_case
summarize_cases = summarize_form_15_cases

__all__ = [
    "analyze_case",
    "analyze_form_15_review_case",
    "summarize_cases",
    "summarize_form_15_cases",
]
