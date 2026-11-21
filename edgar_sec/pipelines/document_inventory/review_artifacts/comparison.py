from __future__ import annotations

from dataclasses import fields

from edgar_sec.domain.document_inventory.models import InventoryEntry

_ENTRY_FIELDS = tuple(field.name for field in fields(InventoryEntry))


def compare_review_analysis_runs(base: dict, new: dict) -> dict:
    base_cases = base["case_map"]
    new_cases = new["case_map"]
    shared_inputs = sorted(set(base_cases) & set(new_cases))
    input_changed_accessions = sorted(
        {key[0] for key in set(base_cases) ^ set(new_cases)}
    )
    row_changes = []
    observation_changes = []
    parser_fingerprint_changes = []
    for key in shared_inputs:
        base_case = base_cases[key]
        new_case = new_cases[key]
        if base_case["parser_fingerprint"] != new_case["parser_fingerprint"]:
            parser_fingerprint_changes.append(
                {
                    "accession": key[0],
                    "base": base_case["parser_fingerprint"],
                    "new": new_case["parser_fingerprint"],
                }
            )
        changed_observations = {
            field: {
                "base": base_case["observations"].get(field),
                "new": new_case["observations"].get(field),
            }
            for field in (
                "status",
                "bundle_url",
                "bundle_size",
                "xbrl_candidate_url",
                "diagnostics",
            )
            if base_case["observations"].get(field)
            != new_case["observations"].get(field)
        }
        if changed_observations:
            observation_changes.append(
                {"accession": key[0], "fields": changed_observations}
            )
        old_rows = {
            (row.get("table_kind"), row.get("row_ordinal")): row
            for row in base_case["entries"]
        }
        new_rows = {
            (row.get("table_kind"), row.get("row_ordinal")): row
            for row in new_case["entries"]
        }
        for row_key in sorted(set(old_rows) | set(new_rows), key=str):
            old = old_rows.get(row_key)
            current = new_rows.get(row_key)
            if old is None or current is None:
                row_changes.append(
                    {
                        "accession": key[0],
                        "table_kind": row_key[0],
                        "row_ordinal": row_key[1],
                        "change": "added" if old is None else "removed",
                    }
                )
                continue
            changed = {
                field: {"base": old.get(field), "new": current.get(field)}
                for field in _ENTRY_FIELDS
                if old.get(field) != current.get(field)
            }
            if changed:
                row_changes.append(
                    {
                        "accession": key[0],
                        "table_kind": row_key[0],
                        "row_ordinal": row_key[1],
                        "change": "changed",
                        "fields": changed,
                    }
                )
    return {
        "base_run": base["run_id"],
        "new_run": new["run_id"],
        "shared_input_count": len(shared_inputs),
        "input_changed_accessions": input_changed_accessions,
        "parser_fingerprint_changes": parser_fingerprint_changes,
        "observation_change_count": len(observation_changes),
        "observation_changes": observation_changes,
        "row_change_count": len(row_changes),
        "row_changes": row_changes,
    }
