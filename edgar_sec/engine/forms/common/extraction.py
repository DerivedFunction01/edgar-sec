from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TypeVar
import xml.etree.ElementTree as ET

from edgar_sec.domain.taxonomy.jurisdictions import edgar_jurisdiction_code
from edgar_sec.engine.forms.common.dates import (
    format_iso_date,
    normalize_iso_date,
)
from edgar_sec.engine.forms.common.numbers import normalize_schema_number

_Record = TypeVar("_Record")


class FieldKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    BOOLEAN = "boolean"
    ENUM = "enum"
    JURISDICTION = "jurisdiction"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    path: str
    kind: FieldKind
    source_attribute: str | None = None
    xml_tag: str | None = None
    required: bool = False
    max_length: int | None = None
    max_occurs: int | None = None
    allowed_values: frozenset[str] = frozenset()
    minimum: str | None = None
    maximum: str | None = None
    max_scale: int | None = None
    date_lexeme: str = "ISO"
    allow_month_year: bool = False
    value_child: bool = False
    strip_currency: bool = False
    strip_units: bool = False
    strip_percent: bool = False
    strip_footnotes: bool = False
    allow_accounting_negative: bool = False
    allow_negative: bool = False
    allow_integral_decimal: bool = False
    require_canonical: bool = False
    anomaly_kind: str | None = None
    detail: str | None = None

    @property
    def tag(self) -> str:
        return self.xml_tag or self.path.rsplit(".", 1)[-1]


@dataclass(frozen=True, slots=True)
class ExtractedValue:
    path: str
    raw_value: str | None
    value: str | None
    issue: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    reported_year_anchor: int | None = None

    def unresolved_record(self) -> dict[str, object] | None:
        return build_unresolved_record(
            self.path,
            self.raw_value if self.value is None else None,
            self.issue,
            self.start_offset,
            self.end_offset,
            self.reported_year_anchor,
        )


def build_unresolved_record(
    path: str,
    raw_value: str | None,
    status: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    reference_year: int | None = None,
) -> dict[str, object] | None:
    return build_scalar_evidence_record(
        path,
        raw_value,
        status=status or "unresolved",
        start_offset=start_offset,
        end_offset=end_offset,
        reference_year=reference_year,
    )


def build_scalar_evidence_record(
    path: str,
    raw_value: str | None,
    *,
    status: str,
    normalized_value: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    reference_year: int | None = None,
) -> dict[str, object] | None:
    if raw_value is None:
        return None
    role = "date" if status == "normalized" else "unresolved"
    record: dict[str, object] = {
        "role": f"normalization.{role}:{path}",
        "content_type": "text/plain",
        "content": raw_value,
        "normalization_status": status,
    }
    if normalized_value is not None:
        record["normalized_value"] = normalized_value
    if start_offset is not None:
        record["start_offset"] = start_offset
    if end_offset is not None:
        record["end_offset"] = end_offset
    if reference_year is not None:
        record["reported_year_anchor"] = reference_year
    return record


def normalize_record_dates(
    record: _Record, paths: Sequence[str], reference_year: int | None = None
) -> _Record:
    normalized, results = normalize_record_fields(
        record,
        tuple(FieldSpec(path, FieldKind.DATE) for path in paths),
        reference_year,
    )
    return replace(
        normalized,
        **{
            path: result.raw_value
            for path, result in zip(paths, results, strict=True)
            if result.value is None
        },
    )


def normalize_record_fields(
    record: _Record,
    specs: Sequence[FieldSpec],
    reference_year: int | None = None,
) -> tuple[_Record, tuple[ExtractedValue, ...]]:
    results = tuple(
        extract_value(
            getattr(record, spec.source_attribute or spec.path),
            spec,
            reference_year=reference_year,
        )
        for spec in specs
    )
    return (
        replace(
            record,
            **{
                spec.source_attribute or spec.path: result.value
                for spec, result in zip(specs, results, strict=True)
            },
        ),
        results,
    )


def _normalize(value: str, spec: FieldSpec, reference_year: int | None) -> str | None:
    if spec.kind is FieldKind.TEXT:
        return value.strip()
    if spec.kind in {FieldKind.INTEGER, FieldKind.DECIMAL}:
        return normalize_schema_number(
            value,
            integer=spec.kind is FieldKind.INTEGER,
            strip_currency=spec.strip_currency,
            strip_units=spec.strip_units,
            strip_percent=spec.strip_percent,
            strip_footnotes=spec.strip_footnotes,
            allow_accounting_negative=spec.allow_accounting_negative,
            allow_negative=spec.allow_negative,
            allow_integral_decimal=spec.allow_integral_decimal,
        )
    if spec.kind is FieldKind.DATE:
        return normalize_iso_date(
            value,
            reference_year,
            allow_month_year=spec.allow_month_year,
        )
    if spec.kind is FieldKind.BOOLEAN:
        normalized = value.strip().lower()
        return normalized if normalized in {"true", "false", "1", "0"} else None
    if spec.kind is FieldKind.ENUM:
        return value.strip()
    if spec.kind is FieldKind.JURISDICTION:
        return normalize_jurisdiction_code(value, spec.allowed_values or None)
    raise ValueError(f"unsupported field kind: {spec.kind}")


def normalize_jurisdiction_code(
    value: str | None,
    allowed_codes: frozenset[str] | None = None,
) -> str | None:
    if not value:
        return None
    candidate = value.strip().upper()
    if allowed_codes is not None and candidate in allowed_codes:
        return candidate
    code = edgar_jurisdiction_code(candidate)
    if code is None or (allowed_codes is not None and code not in allowed_codes):
        return None
    return code


def extract_value(
    raw_value: str | None,
    spec: FieldSpec,
    *,
    reference_year: int | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
) -> ExtractedValue:
    if raw_value is None or not raw_value.strip():
        issue = "required" if spec.required else None
        return ExtractedValue(
            spec.path,
            raw_value,
            None,
            issue,
            start_offset,
            end_offset,
            reference_year,
        )
    normalized = _normalize(raw_value, spec, reference_year)
    issue = None if normalized is not None else f"invalid_{spec.kind.value}"
    if normalized is not None and spec.max_length and len(normalized) > spec.max_length:
        normalized = None
        issue = "max_length"
    if (
        normalized is not None
        and spec.allowed_values
        and normalized not in spec.allowed_values
    ):
        normalized = None
        issue = "choice"
    if normalized is not None and spec.kind in {FieldKind.INTEGER, FieldKind.DECIMAL}:
        try:
            number = Decimal(normalized)
        except InvalidOperation:
            normalized = None
            issue = "invalid_number"
        else:
            if spec.minimum is not None and number < Decimal(spec.minimum):
                normalized = None
                issue = "minimum"
            if spec.maximum is not None and number > Decimal(spec.maximum):
                normalized = None
                issue = "maximum"
            if (
                normalized is not None
                and spec.max_scale is not None
                and len(normalized.partition(".")[2]) > spec.max_scale
            ):
                normalized = None
                issue = "scale"
    return ExtractedValue(
        spec.path,
        raw_value,
        normalized,
        issue,
        start_offset,
        end_offset,
        reference_year,
    )


def validate_values(
    values: Mapping[str, str | Sequence[str] | None],
    specs: Sequence[FieldSpec],
    accession: str,
) -> list[dict[str, str]]:
    anomalies: list[dict[str, str]] = []
    for spec in specs:
        raw = values.get(spec.path)
        candidates = (raw,) if isinstance(raw, str) or raw is None else raw
        present = [value for value in candidates if value is not None and value.strip()]
        if spec.required and not present:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "missing_required_schema_field",
                    "field": spec.path,
                    "detail": spec.detail
                    or "the supplied XML mapping requires this field",
                }
            )
        for value in present:
            result = extract_value(value, spec)
            valid_date_lexeme = (
                spec.kind is FieldKind.DATE
                and result.value is not None
                and format_iso_date(result.value, month_first=spec.date_lexeme == "MDY")
                == value.strip()
            )
            if (
                result.value is not None
                and (spec.kind is not FieldKind.DATE or valid_date_lexeme)
                and (
                    not spec.require_canonical
                    and spec.kind not in {FieldKind.ENUM, FieldKind.JURISDICTION}
                    or result.value == value.strip()
                )
            ):
                continue
            issue = result.issue or "invalid"
            anomaly: dict[str, str] = {
                "accession": accession,
                "kind": spec.anomaly_kind or f"invalid_{spec.path.rsplit('.', 1)[-1]}",
                "field": spec.path,
                "value": value,
                "detail": spec.detail
                or f"{spec.path} violates its schema constraint ({issue})",
            }
            if spec.max_length is not None:
                anomaly["max_length"] = str(spec.max_length)
            anomalies.append(anomaly)
    return anomalies


def validate_xml_values(
    root: ET.Element,
    specs: Sequence[FieldSpec],
    accession: str,
) -> list[dict[str, str]]:
    by_tag: dict[str, list[str]] = {}
    elements = tuple(root.iter())
    for spec in specs:
        matching = [
            element
            for element in elements
            if element.tag.rsplit("}", 1)[-1] == spec.tag
        ]
        for element in matching:
            value_element = element.find("value") if spec.value_child else None
            value = (
                value_element.text if value_element is not None else element.text
            ) or ""
            by_tag.setdefault(spec.path, []).append(value.strip())
    return validate_values(by_tag, specs, accession)


def validate_xml_cardinality(
    root: ET.Element,
    specs: Sequence[FieldSpec],
    accession: str,
    *,
    default_max: int = 1,
) -> list[dict[str, str]]:
    max_occurs = {
        spec.tag: spec.max_occurs for spec in specs if spec.max_occurs is not None
    }
    anomalies: list[dict[str, str]] = []
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in parent:
            tag = child.tag.rsplit("}", 1)[-1]
            counts[tag] = counts.get(tag, 0) + 1
        for tag, count in counts.items():
            maximum = max_occurs.get(tag, default_max)
            if count > maximum:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": f"excess_{tag}",
                        "detail": f"{tag} occurs {count} times; maximum is {maximum}",
                    }
                )
    return anomalies


def validate_xml_schema(
    root: ET.Element,
    specs: Sequence[FieldSpec],
    accession: str,
    *,
    default_max_occurs: int = 1,
) -> list[dict[str, str]]:
    return [
        *validate_xml_values(root, specs, accession),
        *validate_xml_cardinality(
            root, specs, accession, default_max=default_max_occurs
        ),
    ]


def xml_date_is_valid(value: str, *, month_first: bool) -> bool:
    canonical = normalize_iso_date(value)
    if canonical is None:
        return False
    return format_iso_date(canonical, month_first=month_first) == value


__all__ = [
    "ExtractedValue",
    "FieldKind",
    "FieldSpec",
    "build_scalar_evidence_record",
    "build_unresolved_record",
    "extract_value",
    "normalize_record_dates",
    "normalize_record_fields",
    "normalize_jurisdiction_code",
    "validate_values",
    "validate_xml_cardinality",
    "validate_xml_schema",
    "validate_xml_values",
    "xml_date_is_valid",
]
