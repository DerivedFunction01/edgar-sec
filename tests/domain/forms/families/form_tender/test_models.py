from __future__ import annotations

from edgar_sec.domain.forms.families.form_tender.models import TenderKind


def test_tender_kind_values() -> None:
    assert {kind.value for kind in TenderKind} == {
        "schedule_to",
        "solicitation",
        "going_private",
        "issuer_tender_predecessor",
        "third_party_predecessor",
        "foreign_notice",
    }
