"""Pins for the homed form-family scaffold helpers.
Each pin records the legacy per-family behavior the parameterized home must
reproduce: the five empty reports, the 13F none-checked total, the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.family_scaffold import (
    core_status,
    element_int,
    empty_report,
    fields_of,
    first_group,
    merge_sections,
    name_before_label,
    qname,
)
from edgar_sec.engine.tables.ascii_html.model import HorizontalAlign, ResolvedGrid


def test_empty_report_missing_xml_shape(tmp_path: Path) -> None:
    report = empty_report(
        tmp_path / "case-7", "0000123-26-000001", "missing_extracted_xml", ("a", "b")
    )
    assert report == {
        "case_id": "case-7",
        "accession_number": "0000123-26-000001",
        "core_fields": {"a": False, "b": False},
        "anomalies": ["missing_extracted_xml"],
        "review_signals": ["xml_missing"],
        "blank_fields": {},
        "unparsed_sections": [],
    }


def test_empty_report_corrupt_xml_signal(tmp_path: Path) -> None:
    report = empty_report(tmp_path / "c", "acc", "corrupt_xml", ())
    assert report["review_signals"] == ["corrupt_xml"]
    assert report["core_fields"] == {}


def test_core_status_truthy_fields() -> None:
    doc = SimpleNamespace(name="x", count=0, items=[])
    status = core_status(doc, ("name", "count", "items"))
    assert status == {"name": True, "count": False, "items": False}


def test_core_status_none_checked_counts_a_stated_zero() -> None:
    doc = SimpleNamespace(table_entry_total=0, other=None)
    status = core_status(
        doc, ("table_entry_total", "other"), none_checked={"table_entry_total"}
    )
    assert status == {"table_entry_total": True, "other": False}


def test_qname_clark_notation() -> None:
    assert qname("http://x", "tag") == "{http://x}tag"


def test_fields_of_present_and_absent_keys() -> None:
    rep = {"form_x": {"a": 1}}
    assert fields_of(rep, "form_x") == {"a": 1}
    assert fields_of(rep, "form_y") == {}


def test_first_group_match_and_miss() -> None:
    pattern = re.compile(r"id=(\d+)")
    assert first_group(pattern, "xx id=42 yy") == "42"
    assert first_group(pattern, "nothing") is None


def test_element_int_parses_commas_and_rejects_junk() -> None:
    assert element_int(ET.fromstring("<a>1,234</a>")) == 1234
    assert element_int(ET.fromstring("<a>none</a>")) is None
    assert element_int(ET.fromstring("<a/>")) is None
    assert element_int(None) is None


@dataclass(frozen=True)
class _Section:
    role: str
    table_index: int
    raw_node: object
    resolved_grid: ResolvedGrid


def _grid(cell: str) -> ResolvedGrid:
    return ResolvedGrid(
        rows=((cell,),),
        column_alignments=(HorizontalAlign.LEFT,),
        column_widths=(4,),
    )


def test_merge_sections_keeps_existing_identity_and_class() -> None:
    node = object()
    existing = _Section("cover", 3, node, _grid("a"))
    incoming = _Section("cover", 3, object(), _grid("b"))
    merged = merge_sections(existing, incoming)
    assert type(merged) is _Section
    assert merged.role == "cover"
    assert merged.table_index == 3
    assert merged.raw_node is node
    assert merged.resolved_grid is not existing.resolved_grid
    assert merged.resolved_grid is not incoming.resolved_grid


def test_name_before_label_reads_the_preceding_line() -> None:
    lines = ["Acme Holdings Inc", "Name of Issuer"]
    label_re = re.compile(r"Name of Issuer")
    assert name_before_label(lines, label_re) == "Acme Holdings Inc"


def test_name_before_label_absent() -> None:
    lines = ["12345", "Name of Issuer"]
    label_re = re.compile(r"Name of Issuer")
    assert name_before_label(lines, label_re) is None
