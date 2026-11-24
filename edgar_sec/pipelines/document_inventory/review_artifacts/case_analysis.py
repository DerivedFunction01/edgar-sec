from __future__ import annotations

from collections import defaultdict

from edgar_sec.pipelines.document_inventory.review_artifacts.link_findings import (
    _bundle_findings,
    _link_findings,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.records import (
    _finding,
    _int_or_none,
    _is_exhibit,
    _matches_form,
    _row_summary,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.sequence_findings import (
    _form4_path_pairs,
    _sequence_name_findings,
)


def _analyze_case(case: dict) -> list[dict]:
    findings = []
    entries = case["entries"]
    if len(case["filing_forms"]) > 1:
        findings.append(
            _finding(
                case,
                "filing_form_context_ambiguous",
                filing_forms=case["filing_forms"],
            )
        )
    groups = defaultdict(list)
    ordered_by_table = defaultdict(list)
    for row in entries:
        row["sequence_number"] = _int_or_none(row.get("sequence"))
        row["row_number"] = _int_or_none(row.get("row_ordinal"))
        row["type_normalized"] = (row.get("document_type") or "").strip().upper()
        if row["sequence_number"] is not None:
            groups[(row.get("table_kind"), row["sequence_number"])].append(row)
            ordered_by_table[row.get("table_kind")].append(row)
        findings.extend(_link_findings(case, row))
        findings.extend(_sequence_name_findings(case, row))
    findings.extend(_bundle_findings(case))

    for (table_kind, sequence), rows in groups.items():
        if len(rows) > 1:
            findings.append(
                _finding(
                    case,
                    "duplicate_sequence",
                    table_kind=table_kind,
                    sequence=sequence,
                    rows=[_row_summary(row) for row in rows],
                )
            )

    for table_kind, rows in ordered_by_table.items():
        ordered = sorted(rows, key=lambda row: row["row_number"] or 0)
        sequences = [row["sequence_number"] for row in ordered]
        if sequences != sorted(sequences):
            findings.append(
                _finding(
                    case,
                    "out_of_order_sequence",
                    table_kind=table_kind,
                    sequence_rows=[_row_summary(row) for row in ordered],
                )
            )

    seq1_exhibits = [
        row
        for row in entries
        if row["sequence_number"] == 1 and _is_exhibit(row["type_normalized"])
    ]
    for row in seq1_exhibits:
        later_non_exhibits = [
            candidate
            for candidate in entries
            if candidate["table_kind"] == row["table_kind"]
            and candidate["sequence_number"] is not None
            and candidate["sequence_number"] > 1
            and candidate["type_normalized"]
            and not _is_exhibit(candidate["type_normalized"])
        ]
        filing_forms = case["filing_forms"]
        later_form_rows = [
            candidate
            for candidate in later_non_exhibits
            if len(filing_forms) == 1
            and _matches_form(candidate["type_normalized"], filing_forms[0])
        ]
        findings.append(
            _finding(
                case,
                "sequence_one_exhibit_inversion"
                if later_form_rows
                else "sequence_one_exhibit_candidate",
                row=_row_summary(row),
                filing_forms=filing_forms,
                later_non_exhibit_rows=[
                    _row_summary(item) for item in later_non_exhibits
                ],
                later_form_rows=[_row_summary(item) for item in later_form_rows],
            )
        )

    _form4_path_pairs(case, findings)
    for item in case["observations"].get("diagnostics", {}).get("items", []):
        findings.append(
            _finding(
                case,
                "parser_diagnostic",
                diagnostic_code=item.get("code"),
                row_key=item.get("row_key"),
                detail=item.get("detail"),
            )
        )
    suppressed = case["observations"].get("diagnostics", {}).get("suppressed_count", 0)
    if suppressed:
        findings.append(
            _finding(case, "suppressed_parser_diagnostics", count=suppressed)
        )
    if case["status"] == "parsed" and not entries:
        findings.append(_finding(case, "parsed_empty_page"))
    if case["status"] != "parsed":
        findings.append(_finding(case, "parse_not_successful", status=case["status"]))
    expected_count = case["observations"].get("entry_count")
    if expected_count is not None and expected_count != len(entries):
        findings.append(
            _finding(
                case,
                "entry_count_mismatch",
                manifest_entry_count=expected_count,
                csv_entry_count=len(entries),
            )
        )
    return findings
