"""Semantic review analysis and diagnostics for SEC Form N-CEN filings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_ncen.models import FormNCenDocument
from edgar_sec.engine.forms.form_ncen.xml_parser import parse_ncen_xml

_CORE_FIELDS = (
    "registrant_name",
    "file_number",
    "registrant_cik",
    "classification_type",
)


def _core_status(doc: FormNCenDocument) -> dict[str, bool]:
    return {
        "registrant_name": bool(doc.registrant_name),
        "file_number": bool(doc.file_number),
        "registrant_cik": bool(doc.registrant_cik),
        "classification_type": bool(doc.classification_type),
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
    """Analyze a single Form N-CEN review case and return audit metrics."""
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
        doc = parse_ncen_xml(target_xml.read_bytes())
    except Exception as exc:
        return _empty_report(case_dir, accession, f"xml_parse_error: {exc}")

    anomalies: list[str] = []
    signals: list[str] = []
    core_status = _core_status(doc)
    blank_fields = {f: 1 for f, present in core_status.items() if not present}

    if not doc.registrant_name:
        anomalies.append("missing_registrant_name")
    if not doc.file_number:
        anomalies.append("missing_file_number")
    if not doc.directors:
        signals.append("no_directors_listed")
    if doc.custodian_count == 0:
        signals.append("no_custodians_listed")

    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": core_status,
        "anomalies": anomalies,
        "review_signals": signals,
        "blank_fields": blank_fields,
        "unparsed_sections": [],
        "director_rows": len(doc.directors),
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Form N-CEN case reports into a summary."""
    case_count = len(case_reports)
    if case_count == 0:
        return {"family": "N-CEN", "case_count": 0, "anomalies": []}

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
        total_rows += int(rep.get("director_rows", 0))

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
        "family": "N-CEN",
        "case_count": case_count,
        "field_scorecard": field_scorecard,
        "director_rows_total": total_rows,
        "anomalies": all_anomalies,
        "anomaly_count": len(all_anomalies),
        "review_signals": all_signals,
        "review_signal_count": len(all_signals),
    }


__all__ = ["analyze_case", "summarize_cases"]
