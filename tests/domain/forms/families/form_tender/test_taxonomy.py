from __future__ import annotations

from edgar_sec.domain.forms.families.form_tender.models import TenderKind
from edgar_sec.domain.forms.families.form_tender.taxonomy import (
    SCHEDULE_13E3_ITEMS,
    SCHEDULE_13E3_PRIOR_ITEMS,
    SCHEDULE_13E4_ITEMS,
    SCHEDULE_14D1F_ITEMS,
    SCHEDULE_14D1_ITEMS,
    SCHEDULE_14D9_ITEMS,
    SCHEDULE_TO_ITEMS,
    TENDER_TAXONOMY_BY_KIND,
    TENDER_TITLES,
)


def _identifiers(items) -> list[str]:
    return [definition.item for definition in items]


def test_schedule_to_items_are_the_ma_set() -> None:
    assert _identifiers(SCHEDULE_TO_ITEMS) == [f"ITEM {n}" for n in range(1, 14)]
    names = {d.item: d.names for d in SCHEDULE_TO_ITEMS}
    assert names["ITEM 1"] == ("summary term sheet",)
    assert names["ITEM 13"] == ("information required by schedule 13e-3",)


def test_schedule_14d9_items() -> None:
    assert _identifiers(SCHEDULE_14D9_ITEMS) == [f"ITEM {n}" for n in range(1, 10)]
    names = {d.item: d.names for d in SCHEDULE_14D9_ITEMS}
    assert "the solicitation or recommendation" in names["ITEM 4"]


def test_schedule_13e3_items() -> None:
    assert _identifiers(SCHEDULE_13E3_ITEMS) == [f"ITEM {n}" for n in range(1, 17)]
    names = {d.item: d.names for d in SCHEDULE_13E3_ITEMS}
    assert names["ITEM 8"] == ("fairness of the transaction",)


def test_schedule_13e3_prior_items() -> None:
    assert _identifiers(SCHEDULE_13E3_PRIOR_ITEMS) == [
        f"ITEM {n}" for n in range(1, 18)
    ]
    names = {d.item: d.names for d in SCHEDULE_13E3_PRIOR_ITEMS}
    assert names["ITEM 1"] == (
        "issuer and class of security subject to the transaction",
    )
    assert "material to be filed as exhibits" in names["ITEM 17"]


def test_schedule_13e4_items() -> None:
    assert _identifiers(SCHEDULE_13E4_ITEMS) == [f"ITEM {n}" for n in range(1, 10)]
    names = {d.item: d.names for d in SCHEDULE_13E4_ITEMS}
    assert names["ITEM 1"] == ("security and issuer",)


def test_schedule_14d1_items() -> None:
    assert _identifiers(SCHEDULE_14D1_ITEMS) == [f"ITEM {n}" for n in range(1, 12)]
    names = {d.item: d.names for d in SCHEDULE_14D1_ITEMS}
    assert names["ITEM 1"] == ("security and subject company",)


def test_schedule_14d1f_items() -> None:
    assert _identifiers(SCHEDULE_14D1F_ITEMS) == ["ITEM 1", "ITEM 2"]


def test_taxonomy_by_kind_covers_every_kind() -> None:
    assert set(TENDER_TAXONOMY_BY_KIND) == set(TenderKind)
    assert TENDER_TAXONOMY_BY_KIND[TenderKind.SCHEDULE_TO] is SCHEDULE_TO_ITEMS
    assert TENDER_TAXONOMY_BY_KIND[TenderKind.SOLICITATION] is SCHEDULE_14D9_ITEMS
    assert TENDER_TAXONOMY_BY_KIND[TenderKind.GOING_PRIVATE] is SCHEDULE_13E3_ITEMS


def test_tender_titles() -> None:
    assert "schedule to" in TENDER_TITLES
    assert "schedule 13e-3" in TENDER_TITLES
    assert "schedule 14d-1f" in TENDER_TITLES
