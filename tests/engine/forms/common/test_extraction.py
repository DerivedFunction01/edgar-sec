import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.ownership.taxonomy import OWNERSHIP_STATE_CODES
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    extract_value,
    validate_xml_values,
)
from edgar_sec.engine.forms.common.numbers import normalize_schema_number


def test_shared_number_policy_handles_family_decorations_exactly() -> None:
    assert (
        normalize_schema_number(
            "12,000 shares (1)", integer=True, strip_units=True, strip_footnotes=True
        )
        == "12000"
    )
    assert (
        normalize_schema_number("$1,200.50", integer=False, strip_currency=True)
        == "1200.50"
    )
    assert (
        normalize_schema_number(
            "$1,234 thousand",
            integer=False,
            strip_currency=True,
            allow_accounting_negative=True,
            allow_negative=True,
        )
        is None
    )
    assert normalize_schema_number("$1,234", integer=True, strip_units=True) is None
    assert (
        normalize_schema_number(
            "(1,200.50)",
            integer=False,
            allow_accounting_negative=True,
            allow_negative=True,
        )
        == "-1200.50"
    )
    assert (
        normalize_schema_number("12.5", integer=True, allow_integral_decimal=True)
        is None
    )


def test_shared_extraction_normalizes_jurisdiction_name_and_preserves_failure() -> None:
    countries = EDGAR_JURISDICTION_CODES - OWNERSHIP_STATE_CODES
    spec = FieldSpec(
        "rptOwnerCountry",
        FieldKind.JURISDICTION,
        allowed_values=countries,
    )
    assert extract_value("Quebec, Canada", spec).value == "A8"
    unresolved = extract_value("Alaska", spec, start_offset=12, end_offset=18)
    assert unresolved.value is None
    assert unresolved.unresolved_record() == {
        "role": "normalization.unresolved:rptOwnerCountry",
        "content_type": "text/plain",
        "content": "Alaska",
        "normalization_status": "invalid_jurisdiction",
        "start_offset": 12,
        "end_offset": 18,
    }
    assert len(countries) == 278


def test_generic_xml_validation_checks_types_choices_and_date_lexemes() -> None:
    root = ET.fromstring(
        "<formData><units>2.5</units><country>AK</country>"
        "<eventDate>10-19-2026</eventDate></formData>"
    )
    specs = (
        FieldSpec("units", FieldKind.INTEGER, max_length=12),
        FieldSpec("country", FieldKind.ENUM, allowed_values=frozenset({"CA", "NY"})),
        FieldSpec("eventDate", FieldKind.DATE, date_lexeme="MDY"),
    )
    anomalies = validate_xml_values(root, specs, "a1")
    assert [(row["field"], row["value"]) for row in anomalies] == [
        ("units", "2.5"),
        ("country", "AK"),
    ]
