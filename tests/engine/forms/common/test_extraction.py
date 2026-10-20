import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.ownership.taxonomy import OWNERSHIP_STATE_CODES
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    RequiredElement,
    add_field_element,
    build_scalar_evidence_record,
    constraint_issue,
    extract_value,
    normalize_value,
    validate_xml_required,
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


def test_constraint_issue_reports_bounds_without_normalizing() -> None:
    spec = FieldSpec("units", FieldKind.INTEGER, minimum="1", maximum="100")
    assert constraint_issue("50", spec) is None
    assert constraint_issue("0", spec) == "minimum"
    assert constraint_issue("500", spec) == "maximum"
    assert constraint_issue(None, spec) is None


def test_add_field_element_emits_values_and_records_unresolved_evidence() -> None:
    parent = ET.Element("transactionAmounts")
    unresolved: list[dict[str, object]] = []
    spec = FieldSpec("transactionShares", FieldKind.NUMBER, value_child=True)
    add_field_element(parent, spec, "1,000.000", unresolved=unresolved)
    assert parent.find("transactionShares/value").text == "1000"
    assert unresolved == []

    add_field_element(parent, spec, "-500", unresolved=unresolved)
    assert len(parent.findall("transactionShares")) == 1
    assert unresolved[0]["role"] == "normalization.unresolved:transactionShares"
    assert unresolved[0]["content"] == "-500"


def test_add_field_element_keeps_constrained_values_in_the_document() -> None:
    parent = ET.Element("coding")
    unresolved: list[dict[str, object]] = []
    spec = FieldSpec("transactionCode", FieldKind.ENUM, allowed_values=frozenset({"S"}))
    add_field_element(parent, spec, "Z", unresolved=unresolved)
    assert parent.findtext("transactionCode") == "Z"
    assert unresolved[0]["normalization_status"] == "constraint_violation"
    assert unresolved[0]["normalized_value"] == "Z"


def test_required_element_validation_reports_absent_and_empty_nodes() -> None:
    root = ET.fromstring(
        "<formData><coverPageHeader/><items>text</items>"
        "<signatureInfo><title>Officer</title></signatureInfo></formData>"
    )
    anomalies = validate_xml_required(
        root,
        (
            RequiredElement(parent="", name="coverPageHeader", field="cover"),
            RequiredElement(parent="", name="items", field="items"),
            RequiredElement(
                parent="", name="signatureInfo", field="signature", require_text=False
            ),
            RequiredElement(
                parent="signatureInfo", name="date", field="signature.date"
            ),
        ),
        "a1",
    )
    assert [(row["field"], row["kind"]) for row in anomalies] == [
        ("cover", "missing_required_schema_field"),
        ("signature.date", "missing_required_schema_field"),
    ]


def test_normalize_value_applies_the_type_policy_only() -> None:
    spec = FieldSpec("units", FieldKind.INTEGER, minimum="1")
    assert normalize_value("2", spec) == "2"
    assert normalize_value("2", spec) == "2"
    assert normalize_value("0", spec) == "0"


def test_unresolved_evidence_uses_one_record_shape_across_families() -> None:
    ownership = build_scalar_evidence_record(
        "transactionDate", "05/15/24", status="unresolved", reference_year=None
    )
    form_144 = build_scalar_evidence_record(
        "approxSaleDate", "05/15/24", status="unresolved", reference_year=None
    )
    assert ownership is not None and form_144 is not None
    assert set(ownership) == set(form_144)
    assert set(ownership) == {
        "role",
        "content_type",
        "content",
        "normalization_status",
    }
    assert ownership["role"] == "normalization.unresolved:transactionDate"
    assert form_144["role"] == "normalization.unresolved:approxSaleDate"
    assert ownership["content_type"] == form_144["content_type"] == "text/plain"
    assert ownership["content"] == form_144["content"] == "05/15/24"
