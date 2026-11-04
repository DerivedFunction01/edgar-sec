"""Semantic review analysis for SEC Form 25-NSE filings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_25nse.taxonomy import (
    FORM25NSE_RULE_PROVISIONS,
    FORM25NSE_SCHEMA_VERSIONS,
)
from edgar_sec.engine.forms.form_25nse.xml_parser import parse_form_25nse_xml

_CORE_FIELDS = (
    "schemaVersion",
    "fileNumber",
    "descriptionClassSecurity",
    "ruleProvision",
    "signatureName",
    "signatureDate",
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
        "form_25nse": {},
    }


def analyze_case(
    case_dir: Path,
    record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze a single 25-NSE review case and return semantic metrics."""
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
    doc = parse_form_25nse_xml(raw)
    if doc is None:
        return _missing_report(
            case_dir.name, accession, "missing_notification_document"
        )
    fields = {
        "schema_version": doc.schema_version,
        "exchange_cik": doc.exchange.cik,
        "issuer_cik": doc.issuer.cik,
        "issuer_name": doc.issuer.entity_name,
        "file_number": doc.issuer.file_number,
        "rule_provision": doc.rule_provision,
    }
    core_status = {
        "schemaVersion": bool(doc.schema_version),
        "fileNumber": bool(doc.issuer.file_number),
        "descriptionClassSecurity": bool(doc.description_class_security),
        "ruleProvision": bool(doc.rule_provision),
        "signatureName": bool(doc.signature.name),
        "signatureDate": bool(doc.signature.date),
    }
    anomalies: list[str] = []
    if not doc.exchange.cik:
        anomalies.append("missing_exchange_cik")
    if not doc.issuer.cik:
        anomalies.append("missing_issuer_cik")
    if not doc.issuer.file_number:
        anomalies.append("missing_file_number")
    if not doc.description_class_security:
        anomalies.append("missing_class_description")
    if not doc.rule_provision:
        anomalies.append("missing_rule_provision")
    elif doc.rule_provision not in FORM25NSE_RULE_PROVISIONS:
        anomalies.append(f"rule_provision_off_vocabulary: {doc.rule_provision}")
    if not doc.signature.date:
        anomalies.append("missing_signature_date")
    if doc.schema_version and doc.schema_version not in FORM25NSE_SCHEMA_VERSIONS:
        anomalies.append(f"schema_version_unrecognized: {doc.schema_version}")
    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": core_status,
        "anomalies": anomalies,
        "review_signals": [],
        "blank_fields": {f: 1 for f, ok in core_status.items() if not ok},
        "unparsed_sections": [],
        "form_25nse": fields,
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual 25-NSE case analyses into a summary."""
    total = len(case_reports)
    anomaly_counts: Counter[str] = Counter()
    for rep in case_reports:
        anomaly_counts.update(rep.get("anomalies", []))
    versions: Counter[str] = Counter()
    provisions: Counter[str] = Counter()
    for rep in case_reports:
        fields = rep.get("form_25nse", {})
        if fields.get("schema_version"):
            versions[fields["schema_version"]] += 1
        if fields.get("rule_provision"):
            provisions[fields["rule_provision"]] += 1
    return {
        "case_count": total,
        "anomaly_counts": dict(anomaly_counts),
        "form_25nse_scorecard": {
            "schema_version_counts": dict(versions),
            "rule_provision_counts": dict(provisions),
            "parsed_count": sum(1 for r in case_reports if r.get("form_25nse")),
        },
    }


__all__ = ["analyze_case", "summarize_cases"]
