from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import fields
from pathlib import Path

from edgar_sec.domain.document_inventory.models import InventoryEntry
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.document_inventory.review_artifacts.case_analysis import (
    _analyze_case,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.provenance import (
    form_lookup_for_review_records,
)


_ENTRY_FIELDS = tuple(field.name for field in fields(InventoryEntry))


_ANALYSIS_OUTPUTS = ("entries.csv", "observations.json")


def _load_run(
    run_dir: Path,
    accessions: set[str] | None,
    artifacts_root: Path | None,
) -> dict:
    root = run_dir.resolve()
    manifest = root / "manifest.jsonl"
    if not root.is_dir() or not manifest.is_file():
        raise ValueError(f"review run is missing manifest.jsonl: {run_dir}")
    selected_records = []
    for line_number, line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid review manifest line {line_number}: {manifest}"
            ) from exc
        if accessions is None or record.get("accession") in accessions:
            selected_records.append(record)

    form_lookup = form_lookup_for_review_records(selected_records, artifacts_root)
    records = [
        _load_case(
            root, record, form_lookup.get(record["accession"].replace("-", ""), set())
        )
        for record in selected_records
    ]

    finding_counts = Counter(
        finding["code"] for case in records for finding in case["findings"]
    )
    route_counts = Counter(
        finding["route"]
        for case in records
        for finding in case["findings"]
        if finding["code"] == "acquisition_route"
    )
    case_map = {case["key"]: case for case in records}
    if len(case_map) != len(records):
        raise ValueError(f"review run contains duplicate input identities: {root}")
    return {
        "run_id": root.name,
        "cases": records,
        "case_map": case_map,
        "parser_fingerprints": {
            case["parser_fingerprint"] for case in records if case["parser_fingerprint"]
        },
        "finding_counts": finding_counts,
        "route_counts": route_counts,
    }


def _load_case(root: Path, record: dict, filing_forms: set[str]) -> dict:
    accession = record.get("accession")
    request_url = record.get("request_url")
    response_sha256 = record.get("response_sha256")
    if not all(
        isinstance(value, str) and value
        for value in (accession, request_url, response_sha256)
    ):
        raise ValueError(f"review manifest has incomplete input identity: {root}")

    outputs = record.get("outputs") or {}
    files = {}
    for name in _ANALYSIS_OUTPUTS:
        descriptor = outputs.get(name)
        if descriptor is None:
            continue
        output_path = _checked_output_path(root, descriptor.get("path"))
        if not output_path.is_file():
            raise ValueError(f"review output is missing: {output_path}")
        expected = descriptor.get("sha256")
        if not isinstance(expected, str) or file_sha256(output_path) != expected:
            raise ValueError(f"review output digest mismatch: {output_path}")
        files[name] = output_path
    if "observations.json" not in files:
        raise ValueError(f"review observations are missing: {root}")
    if record.get("status") == "parsed" and "entries.csv" not in files:
        raise ValueError(f"parsed review case has no entries.csv: {root}")

    observations_path = files.get("observations.json")
    observations = (
        json.loads(observations_path.read_text(encoding="utf-8"))
        if observations_path
        else {}
    )
    entries_path = files.get("entries.csv")
    entries = []
    if entries_path:
        with entries_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not set(_ENTRY_FIELDS).issubset(
                reader.fieldnames
            ):
                raise ValueError(
                    f"review entries have an invalid schema: {entries_path}"
                )
            entries = list(reader)
    case = {
        "run_id": root.name,
        "key": (accession, request_url, response_sha256),
        "accession": accession,
        "request_url": request_url,
        "response_sha256": response_sha256,
        "parser_fingerprint": record.get("parser_fingerprint"),
        "filing_forms": sorted(filing_forms),
        "status": record.get("status", "unknown"),
        "observations": observations,
        "entries": entries,
        "entry_count": len(entries),
    }
    case["findings"] = _analyze_case(case)
    return case


def _checked_output_path(root: Path, relative: str | None) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"review output has no relative path: {root}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"review output escapes its run directory: {relative}")
    return path
