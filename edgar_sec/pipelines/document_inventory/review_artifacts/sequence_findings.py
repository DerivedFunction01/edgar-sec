from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from edgar_sec.pipelines.document_inventory.review_artifacts.archive_paths import (
    _row_path_kind,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.records import (
    _finding,
    _is_exhibit,
    _row_summary,
)


def _sequence_name_findings(case: dict, row: dict) -> list[dict]:
    sequence = row["sequence_number"]
    filename = (row.get("filename") or "").strip()
    document_type = row["type_normalized"]
    if sequence is None:
        return []
    result = []
    if _is_exhibit(document_type) and sequence >= 2:
        result.append(
            _finding(
                case,
                "secondary_exhibit_sequence",
                row=_row_summary(row),
                route="direct_or_bundle_sequence",
            )
        )
    if sequence in {2, 3} and _is_exhibit(document_type):
        result.append(_finding(case, "sequence_2_or_3_exhibit", row=_row_summary(row)))
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem
    if filename and stem.isdigit() and suffix in {".txt", ".htm", ".html", ".xml"}:
        if int(stem) != sequence:
            result.append(
                _finding(
                    case,
                    "numbered_filename_sequence_mismatch",
                    row=_row_summary(row),
                    filename_sequence=int(stem),
                )
            )
    return result


def _form4_path_pairs(case: dict, findings: list[dict]) -> None:
    groups = defaultdict(list)
    for row in case["entries"]:
        if row["sequence_number"] == 1 and row["type_normalized"] == "4":
            groups[row["table_kind"]].append(row)
    for table_kind, rows in groups.items():
        kinds = {_row_path_kind(row) for row in rows}
        if {"xsl_nested_xml", "flat_xml"} <= kinds:
            findings.append(
                _finding(
                    case,
                    "form4_alternative_primary_paths",
                    table_kind=table_kind,
                    rows=[_row_summary(row) for row in rows],
                    path_kinds=sorted(kinds),
                )
            )
