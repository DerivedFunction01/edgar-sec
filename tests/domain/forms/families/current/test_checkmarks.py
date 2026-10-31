from __future__ import annotations

from edgar_sec.domain.forms.common.vocabulary import (
    FILER_STATUS_GROUP,
    STATUTORY_BINARY_GROUP,
)
from edgar_sec.domain.forms.families.current.checkmarks import (
    EIGHT_K_CHECKBOX_SCHEMA,
    SIX_K_CHECKBOX_SCHEMA,
)


def test_current_checkbox_schemas_are_form_specific() -> None:
    assert SIX_K_CHECKBOX_SCHEMA.family == "6-K"
    assert EIGHT_K_CHECKBOX_SCHEMA.family == "8-K"
    for schema in (SIX_K_CHECKBOX_SCHEMA, EIGHT_K_CHECKBOX_SCHEMA):
        assert schema.groups == (FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP)
        assert schema.constraints

    assert {label.key for label in SIX_K_CHECKBOX_SCHEMA.labels} >= {
        "annual_report_form_20f",
        "annual_report_form_40f",
    }
    assert {label.key for label in EIGHT_K_CHECKBOX_SCHEMA.labels} >= {
        "written_communications_rule_425",
        "soliciting_material_rule_14a12",
        "precommencement_communications_rule_14d2b",
        "precommencement_communications_rule_13e4c",
    }
