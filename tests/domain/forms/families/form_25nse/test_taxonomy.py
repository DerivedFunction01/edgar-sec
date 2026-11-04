from __future__ import annotations

from edgar_sec.domain.forms.families.form_25nse.taxonomy import (
    FORM25NSE_RULE_PROVISIONS,
    FORM25NSE_SCHEMA_VERSIONS,
    FORM25NSE_XML_SPEC,
)


def test_xml_spec_matches_document_schema() -> None:
    assert FORM25NSE_XML_SPEC.root_tags == frozenset({"notificationOfRemoval"})
    assert FORM25NSE_XML_SPEC.namespaces == frozenset({""})


def test_schema_versions_accept_current_and_earlier() -> None:
    assert FORM25NSE_SCHEMA_VERSIONS == frozenset({"X0202", "X0203"})


def test_rule_provisions_match_schema_pattern() -> None:
    assert "17 CFR 240.12d2-2(b)" in FORM25NSE_RULE_PROVISIONS
    assert len(FORM25NSE_RULE_PROVISIONS) == 5
