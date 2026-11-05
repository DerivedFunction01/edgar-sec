"""Rule 425 review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.cover.registrant import extract_commission_file_number

_FILE_NUMBER_RE = re.compile(r"\b(\d{1,3}-\d{4,}(?:-\d{2})?)\b")
_FILE_CAPTION_RE = re.compile(r"commission\s+file\s+(?:no\.?|number)", re.IGNORECASE)
_FILED_BY_RE = re.compile(r"filed\s+by:?\s*\n?\s*([^\n]+)", re.IGNORECASE)
_SUBJECT_RE = re.compile(r"subject\s+company:?\s*\n?\s*([^\n]+)", re.IGNORECASE)
_RULE_425_RE = re.compile(r"rules?\s*(?:\d+\s*(?:and|,)\s*)?425\b", re.IGNORECASE)
_RULE_14A12_RE = re.compile(r"14a-12")


_VALUE_CUT_MARKERS: tuple[str, ...] = (
    " pursuant to ",
    " subject company:",
    " commission file",
)


def _caption_value(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    value = " ".join(match.group(1).split())
    lowered = value.lower()
    for marker in _VALUE_CUT_MARKERS:
        cut = lowered.find(marker)
        if cut > 0:
            value = value[:cut].rstrip(" ,")
            lowered = value.lower()
    return value or None


def _form_425_fields(text: str) -> dict[str, Any]:
    head_text = "\n".join(text.splitlines()[:40])
    return {
        "filer_name": _caption_value(_FILED_BY_RE, head_text),
        "subject_company": _caption_value(_SUBJECT_RE, head_text),
        "commission_file_number": extract_commission_file_number(
            head_text,
            number_pattern=_FILE_NUMBER_RE,
            caption_pattern=_FILE_CAPTION_RE,
        ),
        "rule_425": bool(_RULE_425_RE.search(head_text)),
        "rule_14a_12": bool(_RULE_14A12_RE.search(head_text)),
    }


def analyze_form_425_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single Rule 425 review case producing header diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "425")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="425", text=text
    )
    if rep is None:
        return None

    fields = _form_425_fields(text)
    rep["form_425"] = fields

    if not fields["filer_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_filer_name",
                "no filed-by filer matched in the Rule 425 header",
            )
        )
    if not fields["subject_company"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_subject_company",
                "no subject company matched in the Rule 425 header",
            )
        )
    if not fields["rule_425"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_rule_reference",
                "no Rule 425 reference matched in the header",
            )
        )
    return rep


def summarize_form_425_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Rule 425 case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="425")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_425", {})

    summary["form_425_scorecard"] = {
        "filer_name_count": sum(
            1 for r in case_reports if fields_of(r).get("filer_name")
        ),
        "subject_company_count": sum(
            1 for r in case_reports if fields_of(r).get("subject_company")
        ),
        "commission_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("commission_file_number")
        ),
        "rule_425_count": sum(1 for r in case_reports if fields_of(r).get("rule_425")),
        "rule_14a_12_count": sum(
            1 for r in case_reports if fields_of(r).get("rule_14a_12")
        ),
    }
    return summary


analyze_case = analyze_form_425_review_case
summarize_cases = summarize_form_425_cases

__all__ = [
    "analyze_case",
    "analyze_form_425_review_case",
    "summarize_cases",
    "summarize_form_425_cases",
]
