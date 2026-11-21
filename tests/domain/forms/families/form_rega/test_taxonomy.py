from __future__ import annotations

from edgar_sec.domain.forms.families.form_rega.models import RegAKind
from edgar_sec.domain.forms.families.form_rega.taxonomy import (
    FORM_1SA_ITEMS,
    FORM_1U_ITEMS,
    REGA_ANNUAL_XML_SPEC,
    REGA_EXIT_XML_SPEC,
    REGA_OFFERING_XML_SPEC,
    REGA_SUBMISSION_TYPES,
    kind_of,
    kind_of_form,
)


def test_xml_specs_match_rega_schemas() -> None:
    for spec in (REGA_OFFERING_XML_SPEC, REGA_ANNUAL_XML_SPEC, REGA_EXIT_XML_SPEC):
        assert spec.root_tags == frozenset({"edgarSubmission"})
    assert (
        "http://www.sec.gov/edgar/rega/oneafiler" in REGA_OFFERING_XML_SPEC.namespaces
    )
    assert "http://www.sec.gov/edgar/rega/onekfiler" in REGA_ANNUAL_XML_SPEC.namespaces
    assert "http://www.sec.gov/edgar/rega/onezfiler" in REGA_EXIT_XML_SPEC.namespaces


def test_kind_dispatch_covers_all_types() -> None:
    assert len(REGA_SUBMISSION_TYPES) == 7
    for submission_type in REGA_SUBMISSION_TYPES:
        assert kind_of(submission_type) is not RegAKind.UNKNOWN


def test_kind_dispatch_groups() -> None:
    assert kind_of("1-A") is RegAKind.OFFERING
    assert kind_of("1-A/A") is RegAKind.OFFERING
    assert kind_of("1-A POS") is RegAKind.OFFERING
    assert kind_of("1-K") is RegAKind.ANNUAL_REPORT
    assert kind_of("1-K/A") is RegAKind.ANNUAL_REPORT
    assert kind_of("1-Z") is RegAKind.EXIT_REPORT
    assert kind_of("1-Z/A") is RegAKind.EXIT_REPORT
    assert kind_of("ZZ") is RegAKind.UNKNOWN
    assert kind_of(None) is RegAKind.UNKNOWN


def test_kind_of_form_covers_text_codes() -> None:
    assert kind_of_form("1-A-W") is RegAKind.WITHDRAWAL
    assert kind_of_form("1-A-W/A") is RegAKind.WITHDRAWAL
    assert kind_of_form("1-SA") is RegAKind.SEMI_ANNUAL
    assert kind_of_form("1-SA/A") is RegAKind.SEMI_ANNUAL
    assert kind_of_form("1-U") is RegAKind.CURRENT
    assert kind_of_form("1-U/A") is RegAKind.CURRENT
    assert kind_of_form("1-K") is RegAKind.ANNUAL_REPORT
    assert kind_of_form("8-K") is RegAKind.UNKNOWN


def test_text_item_taxonomies() -> None:
    assert [d.item for d in FORM_1SA_ITEMS] == ["ITEM 1", "ITEM 2", "ITEM 3", "ITEM 4"]
    assert [d.item for d in FORM_1U_ITEMS] == [f"ITEM {n}" for n in range(1, 10)]
