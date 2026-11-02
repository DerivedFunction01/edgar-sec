"""Semantic review analysis and diagnostics for SEC Form D filings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.extraction import local_name

_CORE_FIELDS = (
    "cik",
    "entityName",
    "submissionType",
    "totalOfferingAmount",
    "totalAmountSold",
    "signatureName",
    "signatureDate",
)


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    val = elem.text.strip()
    return val if val else None


def _first_text(elements_by_tag: dict[str, list[ET.Element]], tag: str) -> str | None:
    elems = elements_by_tag.get(tag, ())
    for elem in elems:
        txt = _text(elem)
        if txt is not None:
            return txt
    return None


def _float_val(elements_by_tag: dict[str, list[ET.Element]], tag: str) -> float | None:
    txt = _first_text(elements_by_tag, tag)
    if not txt:
        return None
    try:
        return float(txt.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def analyze_case(
    case_dir: Path,
    record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze a single Form D review case and return semantic audit metrics."""
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
        return {
            "case_id": case_dir.name,
            "accession_number": accession,
            "core_fields": {f: False for f in _CORE_FIELDS},
            "anomalies": ["missing_extracted_xml"],
            "review_signals": ["xml_missing"],
            "blank_fields": {},
            "unparsed_sections": [],
        }

    try:
        tree = ET.parse(target_xml)
        root = tree.getroot()
    except Exception as exc:
        return {
            "case_id": case_dir.name,
            "accession_number": accession,
            "core_fields": {f: False for f in _CORE_FIELDS},
            "anomalies": [f"xml_parse_error: {exc}"],
            "review_signals": ["corrupt_xml"],
            "blank_fields": {},
            "unparsed_sections": [],
        }

    elements_by_tag: dict[str, list[ET.Element]] = {}
    for elem in root.iter():
        elements_by_tag.setdefault(local_name(elem.tag), []).append(elem)

    core_status: dict[str, bool] = {}
    blank_fields: dict[str, int] = {}
    anomalies: list[str] = []
    signals: list[str] = []

    for f in _CORE_FIELDS:
        val = _first_text(elements_by_tag, f)
        present = bool(val)
        core_status[f] = present
        if not present:
            blank_fields[f] = 1

    cik = _first_text(elements_by_tag, "cik")
    if not cik:
        anomalies.append("missing_issuer_cik")
    elif not cik.isdigit():
        anomalies.append(f"malformed_cik: {cik}")

    entity_name = _first_text(elements_by_tag, "entityName")
    if not entity_name:
        anomalies.append("missing_issuer_name")

    tot_off = _float_val(elements_by_tag, "totalOfferingAmount")
    tot_sold = _float_val(elements_by_tag, "totalAmountSold")
    tot_rem = _float_val(elements_by_tag, "totalRemaining")

    if tot_off is not None and tot_off < 0:
        anomalies.append(f"negative_offering_amount: {tot_off}")
    if tot_sold is not None and tot_sold < 0:
        anomalies.append(f"negative_amount_sold: {tot_sold}")

    tot_txt = (_first_text(elements_by_tag, "totalOfferingAmount") or "").lower()
    is_indefinite = "indefinite" in tot_txt or bool(elements_by_tag.get("isIndefinite"))
    if not is_indefinite and tot_off is not None and tot_sold is not None:
        expected_rem = max(0.0, tot_off - tot_sold)
        if tot_rem is not None and abs(tot_rem - expected_rem) > 1.0:
            signals.append(
                f"offering_balance_mismatch: total={tot_off}, sold={tot_sold}, remaining={tot_rem}"
            )

    sig_date = _first_text(elements_by_tag, "signatureDate")
    if not sig_date:
        anomalies.append("missing_signature_date")

    return {
        "case_id": case_dir.name,
        "accession_number": case_dir.name.split("--")[0],
        "core_fields": core_status,
        "anomalies": anomalies,
        "review_signals": signals,
        "blank_fields": blank_fields,
        "unparsed_sections": [],
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Form D case review reports into a summary report."""
    case_count = len(case_reports)
    if case_count == 0:
        return {"family": "D", "case_count": 0, "anomalies": []}

    field_counts = Counter()
    all_anomalies: list[str] = []
    all_signals: list[str] = []

    for rep in case_reports:
        for f, present in rep.get("core_fields", {}).items():
            if present:
                field_counts[f] += 1
        all_anomalies.extend(rep.get("anomalies", []))
        all_signals.extend(rep.get("review_signals", []))

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
        "family": "D",
        "case_count": case_count,
        "field_scorecard": field_scorecard,
        "anomalies": all_anomalies,
        "anomaly_count": len(all_anomalies),
        "review_signals": all_signals,
        "review_signal_count": len(all_signals),
    }


__all__ = ["analyze_case", "summarize_cases"]
