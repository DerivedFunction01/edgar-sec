from __future__ import annotations

from edgar_sec.domain.forms.families.form_mjds.checkmarks import (
    FORM_F7_CHECKBOX_SCHEMA,
    FORM_F9_CHECKBOX_SCHEMA,
    FORM_F10_CHECKBOX_SCHEMA,
    MJDS_AUTOMATIC_LABELS,
    MJDS_ELECTION_LABELS,
)


def test_automatic_schemas_carry_rule_467a_and_shelf_box() -> None:
    assert FORM_F7_CHECKBOX_SCHEMA.family == "F-7"
    assert FORM_F7_CHECKBOX_SCHEMA.labels == MJDS_AUTOMATIC_LABELS
    assert FORM_F7_CHECKBOX_SCHEMA.constraints == ()
    keys = [label.key for label in MJDS_AUTOMATIC_LABELS]
    assert keys == ["rule_467a_upon_filing", "delayed_or_continuous_shelf"]
    for label in MJDS_AUTOMATIC_LABELS:
        assert label.group == "statutory_binary"
        assert label.phrases


def test_election_schemas_carry_the_467b_block() -> None:
    for schema in (FORM_F9_CHECKBOX_SCHEMA, FORM_F10_CHECKBOX_SCHEMA):
        keys = [label.key for label in schema.labels]
        assert keys == [
            "rule_467a_upon_filing",
            "effectiveness_future_date",
            "rule_467b_designated_date",
            "rule_467b_receipt_clearance",
            "rule_467b_notification",
            "delayed_or_continuous_shelf",
        ]
        assert schema.labels == MJDS_ELECTION_LABELS
        names = [c.name for c in schema.constraints]
        assert names == ["effectiveness_election_exclusion"]
        constraint = schema.constraints[0]
        assert constraint.relation == "not_both"
        assert constraint.left == "rule_467a_upon_filing"
        assert constraint.right == "effectiveness_future_date"
