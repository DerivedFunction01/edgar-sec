from __future__ import annotations

from edgar_sec.domain.forms.families.form_drs.models import DrsKind


def test_drs_kind_values() -> None:
    assert {kind.value for kind in DrsKind} == {
        "submission",
        "letter",
    }
