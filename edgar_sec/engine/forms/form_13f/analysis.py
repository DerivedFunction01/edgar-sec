"""Semantic review analysis and diagnostics for SEC Form 13F filings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_13f.models import Form13FDocument
from edgar_sec.engine.forms.common.entities import is_valid_cusip
from edgar_sec.engine.forms.form_13f.xml_parser import parse_form_13f_xml

_CORE_FIELDS = (
    "manager_name",
    "report_type",
    "period_of_report",
    "table_entry_total",
)


def _core_status(doc: Form13FDocument) -> dict[str, bool]:
    return {
        "manager_name": bool(doc.manager_name),
        "report_type": bool(doc.report_type),
        "period_of_report": bool(doc.period_of_report),
        "table_entry_total": doc.table_entry_total is not None,
    }


def _empty_report(case_dir: Path, accession: str, anomaly: str) -> dict[str, Any]:
    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": {f: False for f in _CORE_FIELDS},
        "anomalies": [anomaly],
        "review_signals": [
            "xml_missing" if anomaly == "missing_extracted_xml" else "corrupt_xml"
        ],
        "blank_fields": {},
        "unparsed_sections": [],
    }


def analyze_case(
    case_dir: Path,
    record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze a single Form 13F review case and return semantic audit metrics."""
    target_xml = case_dir / "operations" / "render_to_xml.xml"
    if not target_xml.exists():
        extracted = case_dir / "extracted.xml"
        if extracted.exists():
            target_xml = extracted

    accession = (
        str(record.get("accession", ""))
        if record is not None
        else case_dir.name.split("--")[0]
    )
    if not target_xml.exists():
        return _empty_report(case_dir, accession, "missing_extracted_xml")

    try:
        doc = parse_form_13f_xml(target_xml.read_bytes(), normalize_values=False)
    except Exception as exc:
        return _empty_report(case_dir, accession, f"xml_parse_error: {exc}")

    anomalies: list[str] = []
    signals: list[str] = []
    core_status = _core_status(doc)
    blank_fields = {f: 1 for f, present in core_status.items() if not present}
    has_cover = bool(doc.submission_type or doc.manager_name or doc.report_type)

    if has_cover and not doc.manager_name:
        anomalies.append("missing_manager_name")
    if has_cover and not doc.report_type:
        anomalies.append("missing_report_type")

    malformed = sum(1 for row in doc.holdings if not is_valid_cusip(row.cusip))
    if malformed:
        anomalies.append(f"malformed_cusip_rows: {malformed}")
    negative = sum(1 for row in doc.holdings if (row.value or 0) < 0)
    if negative:
        anomalies.append(f"negative_value_rows: {negative}")

    if doc.holdings and doc.table_entry_total is not None:
        if len(doc.holdings) != doc.table_entry_total:
            signals.append(
                f"holdings_count_mismatch: rows={len(doc.holdings)}, "
                f"total={doc.table_entry_total}"
            )
    if doc.holdings and doc.table_value_total is not None:
        value_sum = sum(row.value or 0 for row in doc.holdings)
        diff = abs(value_sum - doc.table_value_total)
        # Thousands-era totals are stated rounded to whole thousands, so
        # exact equality is not the contract for a complete table.
        if diff > 1000 and diff > 0.001 * doc.table_value_total:
            signals.append(
                f"holdings_value_mismatch: sum={value_sum}, "
                f"total={doc.table_value_total}"
            )
    if not doc.holdings and (doc.table_entry_total or 0) > 0:
        signals.append("holdings_in_companion_document")

    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": core_status,
        "anomalies": anomalies,
        "review_signals": signals,
        "blank_fields": blank_fields,
        "unparsed_sections": [],
        "holdings_rows": len(doc.holdings),
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Form 13F case review reports into a summary report."""
    case_count = len(case_reports)
    if case_count == 0:
        return {"family": "13F", "case_count": 0, "anomalies": []}

    field_counts = Counter()
    all_anomalies: list[str] = []
    all_signals: list[str] = []
    total_rows = 0

    for rep in case_reports:
        for f, present in rep.get("core_fields", {}).items():
            if present:
                field_counts[f] += 1
        all_anomalies.extend(rep.get("anomalies", []))
        all_signals.extend(rep.get("review_signals", []))
        total_rows += int(rep.get("holdings_rows", 0))

    field_scorecard = {
        field: {
            "cases_with_value": field_counts[field],
            "cases_without_value": case_count - field_counts[field],
            "case_missing_percent": round(
                (case_count - field_counts[field]) * 100 / case_count, 2
            ),
        }
        for field in _CORE_FIELDS
    }

    return {
        "family": "13F",
        "case_count": case_count,
        "field_scorecard": field_scorecard,
        "holdings_rows_total": total_rows,
        "anomalies": all_anomalies,
        "anomaly_count": len(all_anomalies),
        "review_signals": all_signals,
        "review_signal_count": len(all_signals),
    }


__all__ = ["analyze_case", "summarize_cases"]
