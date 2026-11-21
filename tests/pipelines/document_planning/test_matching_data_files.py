from __future__ import annotations

import pytest

from edgar_sec.pipelines.document_planning.matching import inventory_rows
from edgar_sec.pipelines.document_planning.profiles import ProfileTarget

from tests.pipelines.document_planning.matching_support import (
    _data_file_entry,
    _inventory_row,
    _placeholder_entry,
)


@pytest.mark.parametrize("vehicle", ["index_html", "filing_summary", "xbrl_package"])
def test_matched_data_file_carries_the_enumeration_vehicle(vehicle: str) -> None:
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(_data_file_entry("EX-101.INS", "inst.xml"), vehicle=vehicle)],
        (ProfileTarget("data_file", "EX-101.INS", False, "data_file:instance"),),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["source_origin"] == "inventory_index"
    assert rows[0]["availability_evidence"] == vehicle


def test_missing_data_file_carries_the_enumeration_vehicle() -> None:
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(_placeholder_entry(), vehicle="filing_summary")],
        (ProfileTarget("data_file", "EX-101.INS", False, "data_file:instance"),),
    )

    assert rows[0]["status"] == "required_missing"
    assert rows[0]["availability_evidence"] == "filing_summary"


def test_synthesized_extracted_instance_matches_and_carries_vehicle() -> None:
    entry = _data_file_entry("XML", "inst_htm.xml")
    entry["description"] = "EXTRACTED XBRL INSTANCE DOCUMENT"
    rows = inventory_rows(
        "plan-1",
        [_inventory_row(entry, vehicle="xbrl_package")],
        (
            ProfileTarget(
                "data_file",
                "extracted_xbrl_instance",
                False,
                "data_file:extracted_xbrl_instance",
            ),
        ),
    )

    assert rows[0]["status"] == "matched"
    assert rows[0]["availability_evidence"] == "xbrl_package"
