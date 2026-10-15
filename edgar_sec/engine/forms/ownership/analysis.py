"""Semantic review analysis for Form 4 ownership documents."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE

_VALID_TRANSACTION_CODES = frozenset(
    {
        "P",
        "S",
        "A",
        "D",
        "F",
        "I",
        "M",
        "C",
        "E",
        "H",
        "O",
        "X",
        "G",
        "L",
        "W",
        "Z",
        "J",
        "U",
        "K",
    }
)


def _element_text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def analyze_ownership_xml(xml_bytes: bytes, accession: str = "") -> dict[str, Any]:
    """Inspect Form 4 XML envelope for tag counts, semantic anomalies, and unparsed sections."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as err:
        return {
            "accession": accession,
            "error": f"xml_parse_error: {err}",
            "element_counts": {},
            "anomalies": [{"kind": "xml_parse_error", "detail": str(err)}],
            "unparsed_sections": [],
        }

    element_counts: Counter[str] = Counter()
    anomalies: list[dict[str, Any]] = []
    unparsed_sections: list[dict[str, Any]] = []

    for elem in root.iter():
        element_counts[elem.tag] += 1

    # Invariant: underlyingSecurityTitle should not contain dates
    for u_elem in root.iter("underlyingSecurityTitle"):
        val_elem = u_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else u_elem)
        if text and (NUMERIC_DATE_RE.search(text) or "|" in text):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "date_in_underlying_security_title",
                    "value": text,
                    "detail": "underlying security title contains date pattern",
                }
            )

    # Invariant: securityTitle should not contain instruction boilerplate
    for s_elem in root.iter("securityTitle"):
        val_elem = s_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else s_elem)
        if text and ("title of" in text.lower() or "instr." in text.lower()):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "boilerplate_in_security_title",
                    "value": text,
                    "detail": "security title contains instruction header text",
                }
            )

    # Invariant: transactionCode must be a recognized SEC code
    for code_elem in root.iter("transactionCode"):
        code = _element_text(code_elem)
        if code and code.upper() not in _VALID_TRANSACTION_CODES:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_transaction_code",
                    "value": code,
                    "detail": f"unknown transaction code '{code}'",
                }
            )

    # Invariant: dates must match numeric date structure
    for date_tag in ("transactionDate", "exerciseDate", "expirationDate"):
        for d_elem in root.iter(date_tag):
            val_elem = d_elem.find("value")
            text = _element_text(val_elem if val_elem is not None else d_elem)
            if text and not NUMERIC_DATE_RE.search(text):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": f"invalid_{date_tag}",
                        "value": text,
                        "detail": f"{date_tag} does not contain recognized date",
                    }
                )

    # Invariant: directOrIndirectOwnership must be D or I
    for own_elem in root.iter("directOrIndirectOwnership"):
        val_elem = own_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else own_elem)
        if text and text.upper() not in ("D", "I"):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_ownership_nature",
                    "value": text,
                    "detail": f"ownership form '{text}' is neither 'D' nor 'I'",
                }
            )

    # Collect unparsed sections with clean sample snippets
    for unp in root.iter("unparsedSection"):
        t_idx = unp.attrib.get("tableIndex", "")
        role = unp.attrib.get("role", "")
        text = _element_text(unp)
        snippet = re.sub(r"\s+", " ", text)[:240].strip()
        unparsed_sections.append(
            {
                "accession": accession,
                "table_index": t_idx,
                "role": role,
                "char_length": len(text),
                "snippet": snippet,
            }
        )

    return {
        "accession": accession,
        "element_counts": dict(sorted(element_counts.items())),
        "anomalies": anomalies,
        "unparsed_sections": unparsed_sections,
    }


def analyze_ownership_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single review case directory producing ownership diagnostics."""
    accession = str(record.get("accession", ""))
    xml_path = case_dir / "operations" / "render_to_xml.xml"
    if not xml_path.is_file():
        return None
    xml_bytes = xml_path.read_bytes()
    return analyze_ownership_xml(xml_bytes, accession=accession)


def summarize_ownership_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Form 4 case analyses into an overall ownership run summary."""
    total_elements: Counter[str] = Counter()
    all_anomalies: list[dict[str, Any]] = []
    all_unparsed: list[dict[str, Any]] = []

    for rep in case_reports:
        for tag, count in rep.get("element_counts", {}).items():
            total_elements[tag] += count
        all_anomalies.extend(rep.get("anomalies", []))
        all_unparsed.extend(rep.get("unparsed_sections", []))

    # Take representative samples of unparsed sections (up to 10 unique snippets)
    seen_snippets: set[str] = set()
    unparsed_samples: list[dict[str, Any]] = []
    for item in all_unparsed:
        snip = item["snippet"]
        if snip not in seen_snippets:
            seen_snippets.add(snip)
            unparsed_samples.append(item)
            if len(unparsed_samples) >= 10:
                break

    return {
        "family": "4",
        "case_count": len(case_reports),
        "element_counts": dict(sorted(total_elements.items(), key=lambda kv: -kv[1])),
        "anomaly_count": len(all_anomalies),
        "anomalies": all_anomalies,
        "unparsed_section_count": len(all_unparsed),
        "unparsed_samples": unparsed_samples,
    }


analyze_case = analyze_ownership_review_case
summarize_cases = summarize_ownership_cases

__all__ = [
    "analyze_case",
    "analyze_ownership_review_case",
    "analyze_ownership_xml",
    "summarize_cases",
    "summarize_ownership_cases",
]
