"""Semantic review analysis and diagnostics for SEC Form 144 filings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.statutory import HEADER_LEAK_RE

_CORE_FIELDS = (
    "issuerName",
    "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
    "securitiesClassTitle",
    "noOfUnitsSold",
    "aggregateMarketValue",
    "approxSaleDate",
    "signature",
)

_BOILERPLATE_TERMS = (
    "sec 1147",
    "instruction",
    "omb number",
    "18 u.s.c.",
    "potential persons",
    "transmit for filing",
)


def _clean_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def analyze_case(case_dir: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    """Analyze a single review case directory producing Form 144 diagnostics."""
    accession = str(record.get("accession", ""))
    xml_path = case_dir / "operations" / "render_to_xml.xml"
    if not xml_path.is_file():
        return None

    try:
        root = ET.fromstring(xml_path.read_bytes())
    except ET.ParseError:
        return {
            "accession": accession,
            "error": "malformed_xml",
            "core_fields": {f: False for f in _CORE_FIELDS},
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "malformed_xml",
                    "detail": "XML parse failed",
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_section_count": 0,
        }

    tag_values: dict[str, list[str]] = {}
    for elem in root.iter():
        clean = _clean_tag(elem.tag)
        if elem.text and elem.text.strip():
            tag_values.setdefault(clean, []).append(elem.text.strip())

    core_presence: dict[str, bool] = {
        field: bool(tag_values.get(field)) for field in _CORE_FIELDS
    }

    anomalies: list[dict[str, Any]] = []
    review_signals: list[dict[str, Any]] = []

    for req in (
        "issuerName",
        "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
        "noOfUnitsSold",
        "signature",
    ):
        if not core_presence.get(req):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": f"missing_{req}",
                    "detail": f"Required field {req!r} is missing",
                }
            )

    for name_field in (
        "issuerName",
        "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
    ):
        for val in tag_values.get(name_field, []):
            lower_val = val.lower()
            if any(
                term in lower_val for term in _BOILERPLATE_TERMS
            ) or HEADER_LEAK_RE.search(val):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "boilerplate_leak",
                        "detail": f"Boilerplate text leaked into {name_field}: {val[:50]!r}",
                    }
                )

    for amt in tag_values.get("noOfUnitsSold", []):
        try:
            if float(amt) <= 0:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "invalid_units",
                        "detail": f"Units sold is zero or negative: {amt}",
                    }
                )
        except ValueError:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_units",
                    "detail": f"Non-numeric units sold: {amt}",
                }
            )

    if tag_values.get("planAdoptionDate"):
        for pd in tag_values["planAdoptionDate"]:
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "10b5_1_plan",
                    "value": pd,
                }
            )

    for gift_flag in tag_values.get("isGiftTransaction", []):
        if gift_flag.upper() == "Y":
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "gift_transaction",
                    "value": "Table I gift transaction reported",
                }
            )

    exchanges = tag_values.get("securitiesExchangeName", [])
    relationships = tag_values.get("relationshipToIssuer", [])

    unparsed_sections: list[dict[str, Any]] = []
    for unp in root.iter():
        if _clean_tag(unp.tag) != "unparsedSection":
            continue
        t_idx = unp.attrib.get("tableIndex", "")
        role = unp.attrib.get("role", "")
        text = "".join(unp.itertext()).strip()
        snippet = " ".join(text.split())[:240].strip()
        lower_snip = snippet.lower()
        is_boilerplate = any(term in lower_snip for term in _BOILERPLATE_TERMS)
        unparsed_sections.append(
            {
                "accession": accession,
                "table_index": t_idx,
                "role": role,
                "char_length": len(text),
                "snippet": snippet,
                "is_boilerplate": is_boilerplate,
            }
        )

    return {
        "accession": accession,
        "error": None,
        "core_fields": core_presence,
        "anomalies": anomalies,
        "review_signals": review_signals,
        "value_frequencies": {
            "exchange": exchanges,
            "relationship": relationships,
        },
        "unparsed_section_count": len(unparsed_sections),
        "unparsed_sections": unparsed_sections,
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Form 144 case analyses into an overall summary report."""
    case_count = max(1, len(case_reports))
    field_counts: Counter[str] = Counter()
    all_anomalies: list[dict[str, Any]] = []
    all_signals: list[dict[str, Any]] = []
    all_unparsed: list[dict[str, Any]] = []
    exchange_freq: Counter[str] = Counter()
    relationship_freq: Counter[str] = Counter()

    for rep in case_reports:
        for f, present in rep.get("core_fields", {}).items():
            if present:
                field_counts[f] += 1
        all_anomalies.extend(rep.get("anomalies", []))
        all_signals.extend(rep.get("review_signals", []))
        all_unparsed.extend(rep.get("unparsed_sections", []))

        vf = rep.get("value_frequencies", {})
        for ex in vf.get("exchange", []):
            exchange_freq[ex.upper()] += 1
        for rel in vf.get("relationship", []):
            relationship_freq[rel] += 1

    substantive_unparsed = [
        item for item in all_unparsed if not item.get("is_boilerplate")
    ]
    boilerplate_unparsed_count = len(all_unparsed) - len(substantive_unparsed)

    unparsed_samples: list[dict[str, Any]] = []
    target_pool = substantive_unparsed if substantive_unparsed else all_unparsed
    for item in target_pool:
        if not any(s["snippet"] == item["snippet"] for s in unparsed_samples):
            unparsed_samples.append(item)
            if len(unparsed_samples) >= 10:
                break

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
        "family": "144",
        "case_count": case_count,
        "field_scorecard": field_scorecard,
        "anomalies": all_anomalies,
        "anomaly_count": len(all_anomalies),
        "review_signals": all_signals,
        "review_signal_count": len(all_signals),
        "unparsed_section_count": len(all_unparsed),
        "boilerplate_unparsed_count": boilerplate_unparsed_count,
        "substantive_unparsed_count": len(substantive_unparsed),
        "unparsed_samples": unparsed_samples,
        "value_frequencies": {
            "exchange": {
                "distinct_values": len(exchange_freq),
                "top_values": [
                    {"value": val, "count": count}
                    for val, count in exchange_freq.most_common(10)
                ],
            },
            "relationship": {
                "distinct_values": len(relationship_freq),
                "top_values": [
                    {"value": val, "count": count}
                    for val, count in relationship_freq.most_common(10)
                ],
            },
        },
    }


__all__ = [
    "analyze_case",
    "summarize_cases",
]
