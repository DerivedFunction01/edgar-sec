from __future__ import annotations

from edgar_sec.domain.forms.families.form_abs_reports.models import (
    FormAbsReportsKind,
)
from edgar_sec.domain.forms.families.form_abs_reports.taxonomy import (
    ABS_REPORTS_ITEMS,
    kind_of,
)


def test_kind_dispatch_by_form_code() -> None:
    assert kind_of("10-D") is FormAbsReportsKind.DISTRIBUTION
    assert kind_of("10-D/A") is FormAbsReportsKind.DISTRIBUTION
    assert kind_of("ABS-15G") is FormAbsReportsKind.SECURITIZER
    assert kind_of("ABS-15G/A") is FormAbsReportsKind.SECURITIZER


def test_union_taxonomy_keeps_both_faces_monotonic() -> None:
    identifiers = [d.item for d in ABS_REPORTS_ITEMS]
    assert identifiers == [
        "PART I",
        "ITEM 1",
        "ITEM 1A",
        "ITEM 1B",
        "ITEM 1.01",
        "ITEM 1.02",
        "ITEM 1.03",
        "PART II",
        "ITEM 2",
        "ITEM 3",
        "ITEM 4",
        "ITEM 5",
        "ITEM 6",
        "ITEM 7",
        "ITEM 8",
        "ITEM 9",
        "ITEM 10",
        "ITEM 2.01",
    ]
    part_one = ABS_REPORTS_ITEMS[0]
    assert "representation and warranty information" in part_one.names
    assert "distribution information" in part_one.names
