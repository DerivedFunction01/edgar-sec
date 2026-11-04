from __future__ import annotations

from edgar_sec.domain.forms.families.form_tender.checkmarks import (
    TENDER_CHECKBOX_SCHEMA,
)


def test_tender_checkbox_schema_properties() -> None:
    assert TENDER_CHECKBOX_SCHEMA.family == "SC TO"
    assert TENDER_CHECKBOX_SCHEMA.groups == ("statutory_binary",)
    assert TENDER_CHECKBOX_SCHEMA.constraints == ()


def test_tender_checkbox_schema_labels() -> None:
    keys = [label.key for label in TENDER_CHECKBOX_SCHEMA.labels]
    assert keys == [
        "fee_offset_rule_0_11",
        "preliminary_communications",
        "third_party_tender_offer",
        "issuer_tender_offer",
        "going_private_transaction",
        "schedule_13d_amendment",
        "final_amendment",
        "cross_border_issuer_tender_offer",
        "cross_border_third_party_tender_offer",
        "connection_solicitation_materials",
        "connection_registration_statement",
        "preliminary_solicitation_copies",
    ]
    for label in TENDER_CHECKBOX_SCHEMA.labels:
        assert label.group == "statutory_binary"
        assert label.phrases
