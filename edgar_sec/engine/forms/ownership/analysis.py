"""Semantic review analysis for Form 4 ownership documents."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.foundation.text.dates import (
    MONTH_PATTERN,
    NUMERIC_DATE_RE,
)

_MONTH_WORD_RE = re.compile(rf"(?i)\b(?:{MONTH_PATTERN})\b")

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

_HEADER_LEAK_PHRASES = (
    "deemed execution",
    "date of original",
    "title of security",
    "individual or joint",
    "price of derivative",
    "amount or number",
    "conversion or exercise",
)

_SIGNATURE_BOILERPLATE_PHRASES = (
    "omb",
    "reminder",
    "potential persons",
    "see instruction",
    "criminal violations",
    "valid omb",
    "intentional misstatements",
)

_STATUTORY_BOILERPLATE_PHRASES = (
    "reminder: report on a separate",
    "potential persons who are to respond",
    "note: file three copies",
    "intentional misstatements",
    "see instruction",
    "form 4",
    "check this box if no longer",
    "table i - non-derivative",
    "table ii - derivative",
    "sec 1474",
    "sec 2474",
    "(over)",
)


def mask_normalized_pattern(text: str) -> str:
    """Mask text into structural placeholders for digits, months, and dates."""
    masked = NUMERIC_DATE_RE.sub("DATE_PATTERN", text)
    masked = _MONTH_WORD_RE.sub("MONTH", masked)
    masked = re.sub(r"\d+", "###", masked)
    return re.sub(r"\s+", " ", masked).strip()


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
            "core_fields": {},
        }

    element_counts: Counter[str] = Counter()
    anomalies: list[dict[str, Any]] = []
    unparsed_sections: list[dict[str, Any]] = []

    for elem in root.iter():
        element_counts[elem.tag] += 1

    # Invariant: underlyingSecurityTitle should not contain dates or column headers
    for u_elem in root.iter("underlyingSecurityTitle"):
        val_elem = u_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else u_elem)
        lower = text.lower()
        if text and (NUMERIC_DATE_RE.search(text) or "|" in text):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "date_in_underlying_security_title",
                    "value": text,
                    "detail": "underlying security title contains date pattern",
                }
            )
        if text and any(header in lower for header in _HEADER_LEAK_PHRASES):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "header_leak_in_underlying_security_title",
                    "value": text,
                    "detail": "underlying security title contains column header text",
                }
            )

    # Invariant: securityTitle should not contain instruction boilerplate or column headers
    for s_elem in root.iter("securityTitle"):
        val_elem = s_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else s_elem)
        lower = text.lower()
        if text and ("title of" in lower or "instr." in lower):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "boilerplate_in_security_title",
                    "value": text,
                    "detail": "security title contains instruction header text",
                }
            )
        if text and any(header in lower for header in _HEADER_LEAK_PHRASES):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "header_leak_in_security_title",
                    "value": text,
                    "detail": "security title contains column header text",
                }
            )

    # Invariant: signatureName should not contain statutory boilerplate
    for sig_name_elem in root.iter("signatureName"):
        text = _element_text(sig_name_elem)
        lower = text.lower()
        if text and any(b in lower for b in _SIGNATURE_BOILERPLATE_PHRASES):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "boilerplate_in_signature_name",
                    "value": text,
                    "detail": "signature name contains statutory boilerplate text",
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

    # Check presence of canonical core fields
    core_fields: dict[str, bool] = {
        "periodOfReport": bool(_element_text(root.find("periodOfReport"))),
        "issuerName": bool(_element_text(root.find("issuer/issuerName"))),
        "issuerTradingSymbol": bool(
            _element_text(root.find("issuer/issuerTradingSymbol"))
        ),
        "rptOwnerName": bool(
            _element_text(root.find("reportingOwner/reportingOwnerId/rptOwnerName"))
        ),
        "signatureName": bool(_element_text(root.find("ownerSignature/signatureName"))),
        "signatureDate": bool(_element_text(root.find("ownerSignature/signatureDate"))),
    }

    # Collect unparsed sections with clean sample snippets
    for unp in root.iter("unparsedSection"):
        t_idx = unp.attrib.get("tableIndex", "")
        role = unp.attrib.get("role", "")
        text = _element_text(unp)
        snippet = re.sub(r"\s+", " ", text)[:240].strip()
        lower_snip = snippet.lower()
        is_boilerplate = any(b in lower_snip for b in _STATUTORY_BOILERPLATE_PHRASES)
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

    field_values: dict[str, list[str]] = {
        "securityTitle": [
            text
            for s in root.iter("securityTitle")
            if (
                text := _element_text(
                    s.find("value") if s.find("value") is not None else s
                )
            )
        ],
        "underlyingSecurityTitle": [
            text
            for u in root.iter("underlyingSecurityTitle")
            if (
                text := _element_text(
                    u.find("value") if u.find("value") is not None else u
                )
            )
        ],
        "signatureName": [
            text for sig in root.iter("signatureName") if (text := _element_text(sig))
        ],
        "officerTitle": [
            text for off in root.iter("officerTitle") if (text := _element_text(off))
        ],
        "rptOwnerName": [
            text for own in root.iter("rptOwnerName") if (text := _element_text(own))
        ],
    }

    return {
        "accession": accession,
        "element_counts": dict(sorted(element_counts.items())),
        "anomalies": anomalies,
        "unparsed_sections": unparsed_sections,
        "core_fields": core_fields,
        "field_values": field_values,
    }


def extract_word_ngrams(text: str, n: int = 2) -> list[str]:
    """Extract lowercased word n-grams from text."""
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9#_]+", text)]
    if n == 1:
        return words
    if len(words) < n:
        return []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


_FIELD_WORD_LIMITS: dict[str, int] = {
    "securityTitle": 7,
    "underlyingSecurityTitle": 7,
    "signatureName": 4,
    "officerTitle": 6,
    "rptOwnerName": 6,
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
    field_counts: Counter[str] = Counter()

    for rep in case_reports:
        for tag, count in rep.get("element_counts", {}).items():
            total_elements[tag] += count
        for field, present in rep.get("core_fields", {}).items():
            if present:
                field_counts[field] += 1
        all_anomalies.extend(rep.get("anomalies", []))
        all_unparsed.extend(rep.get("unparsed_sections", []))

    case_count = max(1, len(case_reports))
    field_completeness = {
        field: f"{field_counts[field]}/{case_count} ({field_counts[field] * 100 // case_count}%)"
        for field in (
            "periodOfReport",
            "issuerName",
            "issuerTradingSymbol",
            "rptOwnerName",
            "signatureName",
            "signatureDate",
        )
    }

    substantive_unparsed = [
        item for item in all_unparsed if not item.get("is_boilerplate")
    ]
    boilerplate_unparsed_count = len(all_unparsed) - len(substantive_unparsed)

    # Take representative samples prioritizing substantive unparsed sections
    seen_snippets: set[str] = set()
    unparsed_samples: list[dict[str, Any]] = []
    target_pool = substantive_unparsed if substantive_unparsed else all_unparsed
    for item in target_pool:
        snip = item["snippet"]
        if snip not in seen_snippets:
            seen_snippets.add(snip)
            unparsed_samples.append(item)
            if len(unparsed_samples) >= 10:
                break

    # Outlier and uncommonness analysis across corpus
    missing_signatures = [
        rep["accession"]
        for rep in case_reports
        if not rep.get("core_fields", {}).get("signatureName")
    ]
    missing_periods = [
        rep["accession"]
        for rep in case_reports
        if not rep.get("core_fields", {}).get("periodOfReport")
    ]
    missing_owners = [
        rep["accession"]
        for rep in case_reports
        if not rep.get("core_fields", {}).get("rptOwnerName")
    ]

    word_count_outliers: list[dict[str, Any]] = []
    field_pattern_counts: dict[str, Counter[str]] = {
        f: Counter()
        for f in (
            "securityTitle",
            "underlyingSecurityTitle",
            "signatureName",
            "officerTitle",
        )
    }
    field_pattern_samples: dict[str, dict[str, str]] = {
        f: {}
        for f in (
            "securityTitle",
            "underlyingSecurityTitle",
            "signatureName",
            "officerTitle",
        )
    }
    field_ngram_counts: dict[str, Counter[str]] = {
        f: Counter()
        for f in (
            "securityTitle",
            "underlyingSecurityTitle",
            "signatureName",
            "officerTitle",
        )
    }

    for rep in case_reports:
        acc = rep.get("accession", "")
        for fld, vals in rep.get("field_values", {}).items():
            limit = _FIELD_WORD_LIMITS.get(fld, 10)
            for v in vals:
                w_list = v.split()
                if len(w_list) > limit:
                    word_count_outliers.append(
                        {
                            "accession": acc,
                            "field": fld,
                            "word_count": len(w_list),
                            "value": v[:120],
                        }
                    )
                if fld in field_pattern_counts:
                    pat = mask_normalized_pattern(v)
                    field_pattern_counts[fld][pat] += 1
                    if pat not in field_pattern_samples[fld]:
                        field_pattern_samples[fld][pat] = acc
                    for ng in extract_word_ngrams(v, n=2):
                        field_ngram_counts[fld][ng] += 1

    common_patterns_by_field: dict[str, list[dict[str, Any]]] = {}
    uncommon_patterns_by_field: dict[str, list[dict[str, Any]]] = {}
    rare_ngrams_by_field: dict[str, list[dict[str, Any]]] = {}

    for fld, pat_counter in field_pattern_counts.items():
        if not pat_counter:
            continue
        common_patterns_by_field[fld] = [
            {"pattern": p, "count": c} for p, c in pat_counter.most_common(5)
        ]
        uncommon_candidates = [
            {
                "pattern": p,
                "count": c,
                "sample_accession": field_pattern_samples[fld][p],
            }
            for p, c in sorted(pat_counter.items(), key=lambda kv: (kv[1], kv[0]))
            if c <= 2 and (case_count < 10 or c < case_count * 0.05)
        ]
        if uncommon_candidates:
            uncommon_patterns_by_field[fld] = uncommon_candidates[:5]

    for fld, ng_counter in field_ngram_counts.items():
        if not ng_counter:
            continue
        rare_candidates = [
            {"ngram": ng, "count": c}
            for ng, c in sorted(ng_counter.items(), key=lambda kv: (kv[1], kv[0]))
            if c <= 2 and (case_count < 10 or c < case_count * 0.05)
        ]
        if rare_candidates:
            rare_ngrams_by_field[fld] = rare_candidates[:5]

    return {
        "family": "4",
        "case_count": len(case_reports),
        "element_counts": dict(sorted(total_elements.items(), key=lambda kv: -kv[1])),
        "anomaly_count": len(all_anomalies),
        "anomalies": all_anomalies,
        "unparsed_section_count": len(all_unparsed),
        "boilerplate_unparsed_count": boilerplate_unparsed_count,
        "substantive_unparsed_count": len(substantive_unparsed),
        "unparsed_samples": unparsed_samples,
        "field_completeness": field_completeness,
        "outliers": {
            "missing_fields": {
                "missing_signatures": {
                    "count": len(missing_signatures),
                    "sample_accessions": missing_signatures[:5],
                },
                "missing_periods": {
                    "count": len(missing_periods),
                    "sample_accessions": missing_periods[:5],
                },
                "missing_owners": {
                    "count": len(missing_owners),
                    "sample_accessions": missing_owners[:5],
                },
            },
            "word_count_outliers": word_count_outliers[:10],
            "common_patterns": common_patterns_by_field,
            "uncommon_patterns": uncommon_patterns_by_field,
            "rare_ngrams": rare_ngrams_by_field,
        },
    }


analyze_case = analyze_ownership_review_case
summarize_cases = summarize_ownership_cases

__all__ = [
    "analyze_case",
    "analyze_ownership_review_case",
    "analyze_ownership_xml",
    "extract_word_ngrams",
    "mask_normalized_pattern",
    "summarize_cases",
    "summarize_ownership_cases",
]
