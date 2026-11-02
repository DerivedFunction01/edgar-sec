"""XML audit and validation rules for beneficial ownership submissions."""

from __future__ import annotations

import re
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.common.missing_values import COMMON_NUMERIC_NULL_POLICY
from edgar_sec.domain.forms.families.beneficial_ownership.identifiers import (
    CUSIP_UNAVAILABLE_POLICY,
)
from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    BENEFICIAL_OWNERSHIP_XML_NAMESPACES,
    SCHEDULE_13G_ITEMS,
    SCHEDULE_13G_XML_NAMESPACE,
)
from edgar_sec.engine.forms.common.entities import is_valid_cusip
from edgar_sec.engine.forms.common.extraction import local_name
from edgar_sec.engine.forms.common.numbers import normalize_schema_number
from edgar_sec.engine.forms.common.statutory import STATUTORY_PAGE_ARTIFACT_RE
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.engine.forms.beneficial_ownership.cover_value_diagnostics import (
    _SEPARATOR_RUN_RE,
    cover_field_has_layout_residue,
    cusip_page_residue_match,
    has_descriptive_numeric_qualifier,
    parsed_field_boilerplate_match,
)
from edgar_sec.engine.forms.beneficial_ownership.field_observations import (
    empty_field_observations,
    field_observations,
)
from edgar_sec.engine.forms.beneficial_ownership.item_subsections import (
    RE_SUBSECTION_SPLIT,
)
from edgar_sec.engine.forms.beneficial_ownership.provenance_analysis import (
    analyze_extraction_provenance,
)
from edgar_sec.engine.forms.beneficial_ownership.schema_analysis import (
    analyze_schema_xml,
)
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import (
    CATEGORICAL_FIELDS,
    CHECKBOX_FIELDS,
    COVER_VALUE_FIELDS,
    FIELD_TAGS,
)
from edgar_sec.engine.forms.common.signatures import (
    clean_signature_name,
    is_valid_signature_name,
)
from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_RE,
    RE_SIGNATURE_DATE_LINE,
    RE_SIGNATURE_HEADING,
)

_NARRATIVE_FIELD_NAMES = frozenset(
    item.item.lower().replace(" ", "") for item in SCHEDULE_13G_ITEMS
)
_MULTI_CLASS_VALUE_RE = re.compile(r"(?i)\bSERIES\s+[A-Z]\b.{0,180}?\d[\d,]*(?:\.\d+)?")
_NUMERIC_COVER_FIELDS = frozenset(
    {
        "soleVotingPower",
        "sharedVotingPower",
        "soleDispositivePower",
        "sharedDispositivePower",
        "aggregateAmountOwned",
        "percentOfClass",
    }
)
_NARRATIVE_NUMERIC_ALT = build_alternation(
    (
        r"see\s+(?:the\s+)?responses?(?:\(s\))?\s+to",
        r"see\s+items?",
        r"see\s+rows?",
        r"see\s+cover\s+pages?(?:\(s\))?",
        r"see\s+each\s+cover",
        r"responses?(?:\(s\))?\s+to\s+items?",
        r"responses?(?:\(s\))?\s+to\s+rows?",
        r"set\s+forth\s+(?:in|on)\s+rows?",
        r"incorporated\s+(?:herein\s+)?by\s+reference",
        r"required\s+by\s+(?:this\s+)?items?",
        r"cover\s+pages?(?:\(s\))?",
        r"rows?\s+(?:\(\d+\)|\d+)\s+of\s+(?:each\s+)?(?:the\s+)?(?:reporting\s+person|cover)",
        r"calculated\s+(?:assuming|based)",
        r"based\s+on\s+a\s+total",
        r"based\s+on\s+the\s+percentages",
        r"based\s+on\s+\d",
        r"as\s+of\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}",
        r"beneficially\s+owned\s+(?:by|are)",
        r"held\s+of\s+record",
        r"investment\s+manager",
        r"shares?\s+of\s+(?:common\s+)?stock",
        r"class\s+[a-z]\s+(?:ordinary\s+)?shares?",
        r"ordinary\s+shares?",
    ),
    compact=False,
)
_RE_NARRATIVE_NUMERIC = re.compile(rf"(?i)\b(?:{_NARRATIVE_NUMERIC_ALT})\b")
_RE_MULTI_ENTITY_ALLOCATION = re.compile(
    r"(?i)(?:(?:\(\d+\)|\b\d+\.|\([a-zivx]+\)|[A-Z0-9,\.\s]{2,40}\s+[-:]\s*\d[\d,]*))"
)


def _is_narrative_numeric_cover(value: str) -> bool:
    if _RE_NARRATIVE_NUMERIC.search(value):
        return True
    if len(_RE_MULTI_ENTITY_ALLOCATION.findall(value)) >= 1 or "\n" in value:
        return True
    return False


def _is_clean_numeric_cover(field: str, value: str) -> bool:
    clean = value.strip(" \t\r\n:.-_")
    if not clean or clean == "0" or COMMON_NUMERIC_NULL_POLICY.is_missing(value):
        return True
    strip_pct = field == "percentOfClass"
    return (
        normalize_schema_number(
            value,
            integer=False,
            strip_percent=strip_pct,
            strip_currency=True,
            strip_units=True,
            strip_footnotes=True,
        )
        is not None
    )


def _text(element: ET.Element) -> str:
    return " ".join(part.strip() for part in element.itertext() if part.strip())


def _elements(root: ET.Element, names: tuple[str, ...]) -> list[ET.Element]:
    wanted = set(names)
    return [element for element in root.iter() if local_name(element.tag) in wanted]


def _source_has_signature(source_text: str) -> bool:
    for heading in RE_SIGNATURE_HEADING.finditer(source_text):
        section = source_text[heading.end() : heading.end() + 3000]
        if CONFORMED_SIGNATURE_RE.search(section):
            return True
        lines = section.splitlines()
        for index, line in enumerate(lines):
            if not RE_SIGNATURE_DATE_LINE.match(line):
                continue
            for name_line in lines[index + 1 : index + 5]:
                candidate = clean_signature_name(name_line)
                if is_valid_signature_name(candidate):
                    return True
    return False


def _boilerplate_match(field: str, value: str) -> str | None:
    if field in _NARRATIVE_FIELD_NAMES or field in {"signature", "commentContent"}:
        return None
    return parsed_field_boilerplate_match(value)


def _is_narrative_element(
    element: ET.Element, parents: dict[ET.Element, ET.Element]
) -> bool:
    current = element
    while current in parents:
        current = parents[current]
        if local_name(current.tag).casefold() in _NARRATIVE_FIELD_NAMES:
            return True
    return False


def analyze_xml(
    xml_text: str,
    accession: str,
    expected_family: str = "",
    source_text: str | None = None,
    unparsed_records: tuple[dict[str, object], ...] = (),
    unparsed_error: str | None = None,
) -> dict[str, Any]:
    """Audit parsed SEC XML tree for conformance, completeness, and anomalies."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        family = "13G" if "13G" in expected_family.upper() else "13D"
        return {
            "accession": accession,
            "form": family,
            "family": family,
            "error": "malformed_xml",
            "field_observations": empty_field_observations(FIELD_TAGS),
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "malformed_xml",
                    "detail": str(error),
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_sections": [],
            "date_normalization_evidence": [],
            "extraction_coverage": None,
        }

    anomalies: list[dict[str, Any]] = []
    review_signals: list[dict[str, Any]] = []
    parents = {child: parent for parent in root.iter() for child in parent}
    namespace, _, _ = root.tag.rpartition("}")
    ns_uri = namespace.removeprefix("{")
    root_name = local_name(root.tag)
    family = (
        "13G"
        if ns_uri == SCHEDULE_13G_XML_NAMESPACE
        or (not ns_uri and "13G" in expected_family.upper())
        else "13D"
    )
    expected = "13G" if "13G" in expected_family.upper() else "13D"
    if (
        root_name != "edgarSubmission"
        or ns_uri not in BENEFICIAL_OWNERSHIP_XML_NAMESPACES
    ):
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_document_envelope",
                "value": root.tag,
                "detail": "root is not a recognized SEC beneficial ownership edgarSubmission envelope",
            }
        )
    if expected_family and family != expected:
        anomalies.append(
            {
                "accession": accession,
                "kind": "form_family_mismatch",
                "value": family,
                "detail": f"rendered XML family {family} differs from expected {expected}",
            }
        )
    anomalies.extend(analyze_schema_xml(root, accession, family))

    direct_children = {local_name(child.tag) for child in root}
    for required in ("headerData", "formData"):
        if required not in direct_children:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": f"missing_{required}",
                    "detail": f"Required XML envelope section {required!r} is missing",
                }
            )

    item_containers = _elements(root, ("items1To7", "narrativeItems", "items"))
    for container in item_containers:
        seen_items: set[str] = set()
        for child in container:
            name = local_name(child.tag).casefold()
            if name not in {f"item{number}" for number in range(1, 11)}:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "unknown_narrative_item",
                        "value": name,
                        "detail": "narrative items container holds unrecognized item tag",
                    }
                )
            elif name in seen_items:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "duplicate_narrative_item",
                        "value": name,
                        "detail": "narrative items container holds duplicate item",
                    }
                )
            seen_items.add(name)
            item_text = _text(child)
            if (
                RE_SIGNATURE_HEADING.search(item_text)
                and CONFORMED_SIGNATURE_RE.search(item_text)
                and not any(
                    _text(element) for element in _elements(root, ("signature",))
                )
            ):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "signature_contained_in_narrative_item",
                        "field": name,
                        "char_length": len(item_text),
                        "snippet": item_text[:240],
                        "detail": "signature evidence is serialized inside a narrative item",
                    }
                )
            if name == "item2":
                subpart_tags = {local_name(e.tag) for e in child}
                if len(subpart_tags) <= 1:
                    for element in child:
                        if (
                            local_name(element.tag) == "filingPersonName"
                            and len(_text(element)) > 240
                            and len(RE_SUBSECTION_SPLIT.findall(_text(element))) >= 2
                        ):
                            value = _text(element)
                            anomalies.append(
                                {
                                    "accession": accession,
                                    "kind": "flattened_narrative_field",
                                    "field": "item2.filingPersonName",
                                    "char_length": len(value),
                                    "snippet": value[:240],
                                    "detail": "Item 2 subparts are collapsed into the filing-person name field",
                                }
                            )
            elif name == "item5":
                subpart_tags = {local_name(e.tag) for e in child}
                if len(subpart_tags) <= 1:
                    for element in child:
                        if (
                            local_name(element.tag) == "percentageOfClassSecurities"
                            and len(_text(element)) > 240
                            and len(RE_SUBSECTION_SPLIT.findall(_text(element))) >= 2
                        ):
                            value = _text(element)
                            anomalies.append(
                                {
                                    "accession": accession,
                                    "kind": "flattened_narrative_field",
                                    "field": "item5.percentageOfClassSecurities",
                                    "char_length": len(value),
                                    "snippet": value[:240],
                                    "detail": "Item 5 subsections are collapsed into the percentage field",
                                }
                            )

    source_has_signature = bool(source_text and _source_has_signature(source_text))
    xml_has_signature = any(
        _text(element) for element in _elements(root, ("signature",))
    )
    if source_has_signature and not xml_has_signature:
        anomalies.append(
            {
                "accession": accession,
                "kind": "signature_missing_from_xml",
                "detail": "normalized source contains signature evidence but XML has no signature value",
            }
        )

    for name in COVER_VALUE_FIELDS:
        for element in _elements(root, FIELD_TAGS[name]):
            value = _text(element)
            boilerplate = (
                None
                if _is_narrative_element(element, parents)
                else _boilerplate_match(name, value)
            )
            if boilerplate is not None:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "boilerplate_in_parsed_field",
                        "field": name,
                        "value": value,
                        "matched_text": boilerplate,
                        "detail": f"parsed field {name!r} contains filing boilerplate",
                    }
                )
            elif (
                value
                and name != "commentContent"
                and (
                    not (
                        name in _NUMERIC_COVER_FIELDS
                        and _is_narrative_numeric_cover(value)
                    )
                    or _SEPARATOR_RUN_RE.search(value) is not None
                )
                and cover_field_has_layout_residue(name, value)
            ):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "cover_field_contamination",
                        "field": name,
                        "value": value,
                        "detail": f"cover field {name!r} contains label or table-border residue",
                    }
                )

    for field in (
        "soleVotingPower",
        "sharedVotingPower",
        "soleDispositivePower",
        "sharedDispositivePower",
        "aggregateAmountOwned",
        "percentOfClass",
    ):
        for element in _elements(root, FIELD_TAGS[field]):
            value = _text(element)
            if (
                not _is_narrative_element(element, parents)
                and _boilerplate_match(field, value) is not None
            ):
                continue
            contamination = (
                not _is_narrative_numeric_cover(value)
                or _SEPARATOR_RUN_RE.search(value) is not None
            ) and cover_field_has_layout_residue(field, value)
            if not value or contamination:
                continue
            multi_class = len(_MULTI_CLASS_VALUE_RE.findall(value)) >= 2
            is_narrative_numeric = _is_narrative_numeric_cover(value)
            if (
                multi_class
                or has_descriptive_numeric_qualifier(value)
                or is_narrative_numeric
            ):
                review_signals.append(
                    {
                        "accession": accession,
                        "kind": (
                            "multi_class_numeric_cover_value"
                            if multi_class
                            else "qualified_numeric_cover_value"
                        ),
                        "field": field,
                        "char_length": len(value),
                        "snippet": value[:240],
                    }
                )
            elif not _is_clean_numeric_cover(field, value):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "invalid_numeric_cover_value",
                        "field": field,
                        "value": value,
                        "detail": f"cover field {field!r} is not a recognizable numeric value",
                    }
                )

    for element in _elements(root, FIELD_TAGS["issuerCusip"]):
        value = _text(element)
        normalized = value.replace(" ", "").replace("-", "")
        if CUSIP_UNAVAILABLE_POLICY.is_missing(value):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "unavailable_cusip_emitted",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "a missing-CUSIP marker is emitted as a CUSIP value",
                }
            )
        elif cusip_page_residue_match(value):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "cover_field_contamination",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "issuer CUSIP contains page or filing-header residue",
                }
            )
        elif value and is_valid_cusip(normalized, length=8):
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "short_cusip_value",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "source provides an eight-character CUSIP without a check digit",
                }
            )
        elif (
            value and len(normalized) == 10 and is_valid_cusip(normalized[:9], length=9)
        ):
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "extended_cusip_value",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "source provides a ten-character CUSIP with an extra check or class digit",
                }
            )
        elif (
            value and len(normalized) == 10 and is_valid_cusip(normalized[:9], length=9)
        ):
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "extended_cusip_value",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "source provides a ten-character CUSIP with an extra check or class digit",
                }
            )
        elif value and not is_valid_cusip(normalized, length=9):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_cusip",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "issuer CUSIP does not contain nine valid characters",
                }
            )

    for name in CHECKBOX_FIELDS:
        for element in _elements(root, (name,)):
            value = _text(element).upper()
            if value and value not in {"Y", "N"}:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "invalid_checkbox_value",
                        "field": name,
                        "value": value,
                        "detail": "Beneficial ownership checkbox value is neither Y nor N",
                    }
                )

    observations = field_observations(root, FIELD_TAGS)
    field_values = {
        field: [
            value for element in _elements(root, names) if (value := _text(element))
        ]
        for field, names in FIELD_TAGS.items()
    }
    value_frequencies = {
        name: [_text(element) for element in _elements(root, (name,)) if _text(element)]
        for name in CATEGORICAL_FIELDS
    }
    unparsed_sections = []
    date_normalization_evidence = []
    for record in unparsed_records:
        value = str(record.get("content", ""))
        role = str(record.get("role", ""))
        if role.startswith("normalization.date:"):
            evidence = {
                "field": role.removeprefix("normalization.date:"),
                "content": value,
                "reported_year_anchor": record.get("reported_year_anchor"),
            }
            for key in ("start_offset", "end_offset"):
                if key in record:
                    evidence[key] = record[key]
            date_normalization_evidence.append(evidence)
            continue
        is_boilerplate = bool(STATUTORY_PAGE_ARTIFACT_RE.search(value))
        section = {
            "accession": accession,
            "role": role,
            "content_type": record.get("content_type", "text/plain"),
            "char_length": len(value),
            "snippet": " ".join(value.split())[:240],
            "is_boilerplate": is_boilerplate,
        }
        for key in ("table_index", "start_offset", "end_offset"):
            if key in record:
                section[key] = record[key]
        unparsed_sections.append(section)
        if role in {"item2.unparsed", "item5.unparsed"} and value.strip():
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "unparsed_narrative_content",
                    "field": role,
                    "char_length": len(value),
                    "snippet": " ".join(value.split())[:240],
                }
            )
        if role.startswith("normalization.unresolved:"):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "unresolved_scalar_normalization",
                    "field": role.removeprefix("normalization.unresolved:"),
                    "snippet": " ".join(value.split())[:240],
                    "detail": "recognized scalar evidence could not be normalized to its XML type",
                }
            )

    provenance_anomalies, extraction_coverage = analyze_extraction_provenance(
        root, source_text, accession, required=False
    )
    anomalies.extend(provenance_anomalies)
    if unparsed_error is not None:
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_unparsed_sections_sidecar",
                "detail": unparsed_error,
            }
        )
    return {
        "accession": accession,
        "form": family,
        "family": family,
        "error": None,
        "field_observations": observations,
        "field_values": field_values,
        "anomalies": anomalies,
        "review_signals": review_signals,
        "value_frequencies": value_frequencies,
        "unparsed_sections": unparsed_sections,
        "date_normalization_evidence": date_normalization_evidence,
        "extraction_coverage": extraction_coverage,
    }
