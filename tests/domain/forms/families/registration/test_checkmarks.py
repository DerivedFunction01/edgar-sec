from __future__ import annotations

from edgar_sec.domain.forms.families.registration.checkmarks import (
    S1_CHECKBOX_SCHEMA,
)


def test_s1_checkbox_schema_properties() -> None:
    assert S1_CHECKBOX_SCHEMA.family == "S-1"
    assert "filer_status" in S1_CHECKBOX_SCHEMA.groups
    assert "statutory_binary" in S1_CHECKBOX_SCHEMA.groups
    assert len(S1_CHECKBOX_SCHEMA.constraints) > 0
