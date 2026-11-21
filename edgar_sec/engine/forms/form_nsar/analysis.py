"""Form NSAR review analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)

_ANSWER_LINE_RE = re.compile(r"^\s*(\d{3})\s+([A-Z])\d{6}\s+(.*?)\s*$")


def _nsar_fields(text: str) -> dict[str, Any]:
    """Extract the keyed identity answers from an NSAR answer file."""
    answers: dict[str, str] = {}
    answer_lines = 0
    for line in text.splitlines():
        match = _ANSWER_LINE_RE.match(line)
        if match is None:
            continue
        answer_lines += 1
        key = f"{match.group(1)}{match.group(2)}"
        if key not in answers and match.group(3):
            answers[key] = match.group(3)
    return {
        "registrant_name": answers.get("001A"),
        "file_number": answers.get("001B"),
        "report_period": answers.get("000B"),
        "cik": answers.get("000C"),
        "answer_lines": answer_lines,
    }


def analyze_form_nsar_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single NSAR review case producing answer diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "NSAR-B")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="NSAR", text=text
    )
    if rep is None:
        return None
    fields = _nsar_fields(text)
    rep["form_nsar"] = fields

    if not fields["answer_lines"]:
        rep["anomalies"].append(
            anomaly_record(
                "no_answer_lines",
                "no keyed answer lines matched in the NSAR document",
            )
        )
    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name at answer 001A",
            )
        )
    if not fields["file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_file_number",
                "no Investment Company Act file number at answer 001B",
            )
        )
    return rep


def summarize_form_nsar_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual NSAR case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="NSAR")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_nsar", {})

    summary["form_nsar_scorecard"] = {
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("file_number")
        ),
        "answer_lines_total": sum(
            int(fields_of(r).get("answer_lines", 0)) for r in case_reports
        ),
    }
    return summary


analyze_case = analyze_form_nsar_review_case
summarize_cases = summarize_form_nsar_cases

__all__ = [
    "analyze_case",
    "analyze_form_nsar_review_case",
    "summarize_cases",
    "summarize_form_nsar_cases",
]
