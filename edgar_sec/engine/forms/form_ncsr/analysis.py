"""Form N-CSR review analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.ica_head import ica_cover_fields


def analyze_form_ncsr_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single N-CSR review case producing cover diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "N-CSR")
    rep = analyze_form_case(case_dir, record, form=resolved_form, family="N-CSR")
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    fields = ica_cover_fields(text.splitlines())
    rep["form_ncsr"] = fields

    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the N-CSR cover",
            )
        )
    if not fields["file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_file_number",
                "no Investment Company Act file number matched on the cover",
            )
        )
    return rep


def summarize_form_ncsr_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual N-CSR case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="N-CSR")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_ncsr", {})

    summary["form_ncsr_scorecard"] = {
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("file_number")
        ),
        "report_period_count": sum(
            1 for r in case_reports if fields_of(r).get("report_period")
        ),
    }
    return summary


analyze_case = analyze_form_ncsr_review_case
summarize_cases = summarize_form_ncsr_cases

__all__ = [
    "analyze_case",
    "analyze_form_ncsr_review_case",
    "summarize_cases",
    "summarize_form_ncsr_cases",
]
