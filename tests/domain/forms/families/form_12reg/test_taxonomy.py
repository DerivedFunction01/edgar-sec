from __future__ import annotations

from edgar_sec.domain.forms.families.form_12reg.models import Form12RegKind
from edgar_sec.domain.forms.families.form_12reg.taxonomy import FORM_8A_ITEMS, kind_of


def test_kind_dispatch_by_form_code() -> None:
    assert kind_of("25") is Form12RegKind.NOTIFICATION
    assert kind_of("25/A") is Form12RegKind.NOTIFICATION
    assert kind_of("8-A12B") is Form12RegKind.REGISTRATION
    assert kind_of("8A12BEF") is Form12RegKind.REGISTRATION
    assert kind_of("8-B12B") is Form12RegKind.PREDECESSOR_REGISTRATION
    assert kind_of("8-B12G") is Form12RegKind.PREDECESSOR_REGISTRATION


def test_two_item_taxonomy() -> None:
    assert [d.item for d in FORM_8A_ITEMS] == ["ITEM 1", "ITEM 2"]
    assert "description of securities" in FORM_8A_ITEMS[0].names[0]
