"""Semantic review analysis for SEC Form C filings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_c.models import FormCKind
from edgar_sec.domain.forms.families.form_c.taxonomy import FORMC_SUBMISSION_TYPES
from edgar_sec.engine.forms.form_c.xml_parser import parse_form_c_xml

_CORE_FIELDS = (
    "submissionType",
    "filerCik",
    "issuerName",
    "commissionFileNumber",
)


def _missing_report(case_id: str, accession: str, anomaly: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "accession_number": accession,
        "core_fields": {f: False for f in _CORE_FIELDS},
        "anomalies": [anomaly],
        "review_signals": ["xml_missing"],
        "blank_fields": {},
        "unparsed_sections": [],
        "form_c": {},
    }


def analyze_case(
    case_dir: Path,
    record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze a single Form C review case and return semantic metrics."""
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
        return _missing_report(case_dir.name, accession, "missing_extracted_xml")
    raw = target_xml.read_bytes()
    try:
        ET.fromstring(raw)
    except ET.ParseError as exc:
        report = _missing_report(case_dir.name, accession, f"xml_parse_error: {exc}")
        report["review_signals"] = ["corrupt_xml"]
        return report
    doc = parse_form_c_xml(raw)
    if doc is None:
        return _missing_report(case_dir.name, accession, "missing_submission_document")
    fields = {
        "submission_type": doc.submission_type,
        "kind": doc.kind.value,
        "filer_ciks": list(doc.filer_ciks),
        "issuer_name": doc.issuer.name,
        "commission_cik": doc.issuer.commission_cik,
        "commission_file_number": doc.issuer.commission_file_number,
        "co_issuer_count": doc.issuer.co_issuer_count,
        "has_offering_information": doc.has_offering_information,
        "has_progress_update": doc.has_progress_update,
        "has_annual_financials": doc.has_annual_financials,
    }
    core_status = {
        "submissionType": bool(doc.submission_type),
        "filerCik": bool(doc.filer_ciks),
        "issuerName": bool(doc.issuer.name),
        "commissionFileNumber": bool(doc.issuer.commission_file_number),
    }
    anomalies: list[str] = []
    if not doc.submission_type:
        anomalies.append("missing_submission_type")
    elif doc.submission_type.strip().upper() not in FORMC_SUBMISSION_TYPES:
        anomalies.append(f"submission_type_off_vocabulary: {doc.submission_type}")
    if doc.kind is FormCKind.UNKNOWN:
        anomalies.append("unknown_kind")
    if not doc.filer_ciks:
        anomalies.append("missing_filer_cik")
    if not doc.issuer.name:
        anomalies.append("missing_issuer_name")
    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": core_status,
        "anomalies": anomalies,
        "review_signals": [],
        "blank_fields": {f: 1 for f, ok in core_status.items() if not ok},
        "unparsed_sections": [],
        "form_c": fields,
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Form C case analyses into a summary."""
    anomaly_counts: Counter[str] = Counter()
    for rep in case_reports:
        anomaly_counts.update(rep.get("anomalies", []))
    kinds: Counter[str] = Counter()
    types: Counter[str] = Counter()
    for rep in case_reports:
        fields = rep.get("form_c", {})
        if fields.get("kind"):
            kinds[fields["kind"]] += 1
        if fields.get("submission_type"):
            types[fields["submission_type"]] += 1
    return {
        "case_count": len(case_reports),
        "anomaly_counts": dict(anomaly_counts),
        "form_c_scorecard": {
            "kind_counts": dict(kinds),
            "submission_type_counts": dict(types),
            "parsed_count": sum(1 for r in case_reports if r.get("form_c")),
            "offering_information_count": sum(
                1
                for r in case_reports
                if r.get("form_c", {}).get("has_offering_information")
            ),
            "progress_update_count": sum(
                1
                for r in case_reports
                if r.get("form_c", {}).get("has_progress_update")
            ),
            "annual_financials_count": sum(
                1
                for r in case_reports
                if r.get("form_c", {}).get("has_annual_financials")
            ),
        },
    }


__all__ = ["analyze_case", "summarize_cases"]
