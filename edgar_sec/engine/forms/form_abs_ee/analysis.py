"""Semantic review analysis for ABS-EE companion exhibits."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.form_abs_ee.stream import (
    probe_asset_data_root,
    summarize_asset_data,
)

_CORE_FIELDS = ("assetDataRoot", "assetRecords")


def _locate_primary(case_dir: Path) -> Path | None:
    operations = case_dir / "operations"
    if not operations.exists():
        return None
    for name in ("render_to_xml.xml", "raw.xml"):
        candidate = operations / name
        if candidate.exists():
            return candidate
    raws = sorted(p for p in operations.glob("raw.*") if p.suffix != ".json")
    return raws[0] if raws else None


def _missing_report(case_id: str, accession: str, anomaly: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "accession_number": accession,
        "core_fields": {f: False for f in _CORE_FIELDS},
        "anomalies": [anomaly],
        "review_signals": ["xml_missing"],
        "blank_fields": {},
        "unparsed_sections": [],
        "form_abs_ee": {},
    }


def analyze_case(
    case_dir: Path,
    record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze a single ABS-EE review case by streaming its primary."""
    accession = (
        str(record.get("accession", ""))
        if record is not None
        else case_dir.name.split("--")[0]
    )
    primary = _locate_primary(case_dir)
    if primary is None:
        return _missing_report(case_dir.name, accession, "missing_extracted_xml")
    if probe_asset_data_root(primary) is None:
        head = primary.read_bytes()[:4096]
        anomaly = "xml_parse_error" if b"<" in head else "missing_asset_data_document"
        return _missing_report(case_dir.name, accession, anomaly)
    summary = summarize_asset_data(primary)
    if summary is None:
        return _missing_report(case_dir.name, accession, "unrecognized_root")
    fields = {
        "exhibit_kind": summary.kind.value,
        "asset_class": summary.asset_class,
        "root_tag": summary.root_tag,
        "record_count": summary.record_count,
        "comment_count": summary.comment_count,
        "comment_chars": summary.comment_chars,
        "cdata_sections": summary.cdata_sections,
    }
    anomalies: list[str] = []
    if summary.kind.value == "EX-102" and summary.record_count == 0:
        anomalies.append("no_asset_records")
    if (
        summary.kind.value == "EX-103"
        and summary.record_count == 0
        and summary.comment_count == 0
        and summary.cdata_sections == 0
    ):
        anomalies.append("no_narrative_content")
    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": {
            "assetDataRoot": True,
            "assetRecords": summary.record_count > 0
            or summary.comment_count > 0
            or summary.cdata_sections > 0,
        },
        "anomalies": anomalies,
        "review_signals": [],
        "blank_fields": {},
        "unparsed_sections": [],
        "form_abs_ee": fields,
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual ABS-EE case analyses into a summary."""
    anomaly_counts: Counter[str] = Counter()
    for rep in case_reports:
        anomaly_counts.update(rep.get("anomalies", []))
    kinds: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    total_records = 0
    for rep in case_reports:
        fields = rep.get("form_abs_ee", {})
        if fields.get("exhibit_kind"):
            kinds[fields["exhibit_kind"]] += 1
        if fields.get("asset_class"):
            classes[fields["asset_class"]] += 1
        total_records += int(fields.get("record_count") or 0)
    return {
        "case_count": len(case_reports),
        "anomaly_counts": dict(anomaly_counts),
        "form_abs_ee_scorecard": {
            "kind_counts": dict(kinds),
            "asset_class_counts": dict(classes),
            "parsed_count": sum(1 for r in case_reports if r.get("form_abs_ee")),
            "total_asset_records": total_records,
            "cases_with_comments": sum(
                1 for r in case_reports if r.get("form_abs_ee", {}).get("comment_count")
            ),
        },
    }


__all__ = ["analyze_case", "summarize_cases"]
