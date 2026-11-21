from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import fields
from pathlib import Path
from urllib.parse import unquote, urlsplit

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.document_inventory.models import InventoryEntry
from edgar_sec.domain.sec_urls import (
    DEFAULT_ARCHIVE_URL_POLICY,
    resolve_sec_href,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.document_inventory.review_artifacts.comparison import (
    compare_review_analysis_runs,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.provenance import (
    form_lookup_for_review_records,
)

_EXHIBIT_TYPES = ("EX-", "EX ")
_EXHIBIT_NAMES = {"GRAPHIC", "ZIP"}
_ENTRY_FIELDS = tuple(field.name for field in fields(InventoryEntry))
_ANALYSIS_OUTPUTS = ("entries.csv", "observations.json")


def analyze_review_runs(
    run_directories: list[Path],
    *,
    artifacts_root: Path | None = None,
    accessions: set[str] | None = None,
) -> dict:
    if not run_directories:
        raise ValueError("at least one review run is required")
    run_ids = [path.name for path in run_directories]
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("review run identifiers must be unique")

    runs = [_load_run(path, accessions, artifacts_root) for path in run_directories]
    comparisons = [compare_review_analysis_runs(runs[0], run) for run in runs[1:]]
    counts = Counter(
        finding["code"]
        for run in runs
        for case in run["cases"]
        for finding in case["findings"]
    )
    routes = Counter(
        finding["route"]
        for run in runs
        for case in run["cases"]
        for finding in case["findings"]
        if finding["code"] == "acquisition_route"
    )
    return {
        "schema_version": 1,
        "network_requests": 0,
        "baseline_run": runs[0]["run_id"],
        "runs": [
            {
                "run_id": run["run_id"],
                "case_count": len(run["cases"]),
                "parser_fingerprints": sorted(run["parser_fingerprints"]),
                "entry_count": sum(case["entry_count"] for case in run["cases"]),
                "filing_form_context_cases": sum(
                    len(case["filing_forms"]) == 1 for case in run["cases"]
                ),
                "findings": dict(sorted(run["finding_counts"].items())),
                "routes": dict(sorted(run["route_counts"].items())),
            }
            for run in runs
        ],
        "comparisons": comparisons,
        "finding_counts": dict(sorted(counts.items())),
        "acquisition_routes": dict(sorted(routes.items())),
        "findings": [
            finding
            for run in runs
            for case in run["cases"]
            for finding in case["findings"]
        ],
    }


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


def _link_findings(case: dict, row: dict) -> list[dict]:
    href = (row.get("href") or "").strip()
    archive_url = (row.get("archive_url") or "").strip()
    sequence = row["sequence_number"]
    bundle_url = case["observations"].get("bundle_url")
    target = resolve_sec_href(case["request_url"], href) if href else None
    direct_matches = bool(
        archive_url and _matches_accession_archive_path(archive_url, case)
    )
    href_matches = bool(target and _matches_accession_archive_path(target, case))
    bundle_matches = bool(
        bundle_url and _matches_accession_bundle_path(bundle_url, case)
    )
    route = (
        "direct"
        if direct_matches
        else "observed_href_unresolved"
        if href_matches
        else "bundle_sequence"
        if bundle_matches and sequence and sequence > 0
        else "unresolved"
    )
    result = [
        _finding(
            case,
            "acquisition_route",
            row=_row_summary(row),
            route=route,
            bundle_url=bundle_url if route == "bundle_sequence" else None,
        )
    ]
    if sequence is None:
        result.append(_finding(case, "missing_sequence", row=_row_summary(row)))
    if not (row.get("filename") or "").strip():
        result.append(_finding(case, "missing_filename", row=_row_summary(row)))
    if not href:
        result.append(_finding(case, "missing_href", row=_row_summary(row)))
        return result

    parsed = urlsplit(target)
    hostname = (parsed.hostname or "").lower()
    if hostname not in DEFAULT_ARCHIVE_URL_POLICY.allowed_hosts:
        result.append(
            _finding(case, "non_sec_href_origin", row=_row_summary(row), url=target)
        )
    if parsed.scheme.lower() not in DEFAULT_ARCHIVE_URL_POLICY.allowed_schemes:
        result.append(
            _finding(case, "href_scheme_not_https", row=_row_summary(row), url=target)
        )
    try:
        has_port = parsed.port is not None
    except ValueError:
        has_port = True
    if parsed.username is not None or parsed.password is not None or has_port:
        result.append(
            _finding(
                case, "href_authority_not_canonical", row=_row_summary(row), url=target
            )
        )
    decoded_segments = [unquote(part) for part in parsed.path.split("/")]
    if any(
        segment in {".", ".."} or "/" in segment or "\\" in segment
        for segment in decoded_segments
    ):
        result.append(
            _finding(case, "href_path_traversal", row=_row_summary(row), url=target)
        )
    if parsed.username is not None or parsed.password is not None:
        result.append(
            _finding(case, "href_userinfo", row=_row_summary(row), url=target)
        )
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    data_index = next(
        (index for index, part in enumerate(parts) if part.lower() == "data"), None
    )
    source_cik = _source_archive_cik(case["request_url"])
    archive_cik = None
    path_accession = None
    if data_index is not None and len(parts) > data_index + 2:
        archive_cik = parts[data_index + 1]
        path_accession = parts[data_index + 2].removesuffix("-index.html")
    accession_digits = case["accession"].replace("-", "")
    if path_accession is None or path_accession != accession_digits:
        result.append(
            _finding(
                case,
                "href_accession_path_mismatch",
                row=_row_summary(row),
                url=target,
                path_accession=path_accession,
            )
        )
    if archive_cik and source_cik and archive_cik != source_cik:
        result.append(
            _finding(
                case,
                "archive_cik_differs_from_source",
                row=_row_summary(row),
                source_cik=source_cik,
                archive_cik=archive_cik,
                accession_path_matches=path_accession == accession_digits,
            )
        )
    if (
        parsed.path.endswith("/")
        or (data_index is not None and len(parts) <= data_index + 2)
        or (
            path_accession
            and path_accession == accession_digits
            and len(parts) == data_index + 3
        )
    ):
        result.append(
            _finding(case, "directory_only_href", row=_row_summary(row), url=target)
        )

    filename = (row.get("filename") or "").strip()
    leaf = unquote(parts[-1]) if parts else ""
    if filename and leaf and filename.casefold() != leaf.casefold():
        result.append(
            _finding(
                case,
                "display_filename_differs_from_href_leaf",
                row=_row_summary(row),
                href_leaf=leaf,
            )
        )

    extension = Path(parsed.path).suffix.lower()
    xsl_path = any(part.lower().startswith("xsl") for part in parts)
    if xsl_path and extension == ".xml":
        path_kind = "xsl_nested_xml"
    elif extension == ".xml":
        path_kind = "flat_xml"
    elif extension in {".htm", ".html"}:
        path_kind = "html"
    else:
        path_kind = "other"
    if path_kind in {"xsl_nested_xml", "flat_xml", "html"}:
        result.append(
            _finding(
                case,
                "document_path_kind",
                row=_row_summary(row),
                kind=path_kind,
                url=target,
            )
        )
    if archive_url:
        resolved_archive = urlsplit(archive_url)
        archive_host = (resolved_archive.hostname or "").lower()
        if archive_host not in {"sec.gov", "www.sec.gov"}:
            result.append(
                _finding(
                    case,
                    "non_sec_archive_url_origin",
                    row=_row_summary(row),
                    archive_url=archive_url,
                )
            )
        if resolved_archive.path != parsed.path:
            result.append(
                _finding(
                    case,
                    "archive_url_differs_from_href",
                    row=_row_summary(row),
                    href_url=target,
                    archive_url=archive_url,
                )
            )
        if not direct_matches:
            result.append(
                _finding(
                    case,
                    "archive_url_not_accession_scoped",
                    row=_row_summary(row),
                    archive_url=archive_url,
                )
            )
    return result


def _bundle_findings(case: dict) -> list[dict]:
    bundle_url = case["observations"].get("bundle_url")
    if not bundle_url:
        return []
    target = resolve_sec_href(case["request_url"], bundle_url)
    parsed = urlsplit(target)
    findings = []
    if (parsed.hostname or "").lower() not in DEFAULT_ARCHIVE_URL_POLICY.allowed_hosts:
        findings.append(_finding(case, "non_sec_bundle_origin", bundle_url=target))
    if parsed.scheme.lower() not in DEFAULT_ARCHIVE_URL_POLICY.allowed_schemes:
        findings.append(_finding(case, "bundle_scheme_not_https", bundle_url=target))
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    data_index = next(
        (index for index, part in enumerate(parts) if part.lower() == "data"), None
    )
    accession_digits = case["accession"].replace("-", "")
    bundle_accession, bundle_leaf = _bundle_path_identity(parts, data_index)
    if bundle_accession != accession_digits:
        findings.append(
            _finding(
                case,
                "bundle_accession_path_mismatch",
                bundle_url=target,
                path_accession=bundle_accession,
            )
        )
    source_cik = _source_archive_cik(case["request_url"])
    bundle_cik = (
        parts[data_index + 1]
        if data_index is not None and len(parts) > data_index + 1
        else None
    )
    if bundle_cik and source_cik and bundle_cik != source_cik:
        findings.append(
            _finding(
                case,
                "bundle_archive_cik_differs_from_source",
                bundle_url=target,
                source_cik=source_cik,
                archive_cik=bundle_cik,
                accession_path_matches=bundle_accession == accession_digits,
            )
        )
    if bundle_accession == accession_digits and not bundle_leaf.lower().endswith(
        ".txt"
    ):
        findings.append(_finding(case, "bundle_url_not_text_file", bundle_url=target))
    return findings


def _matches_accession_archive_path(url: str, case: dict) -> bool:
    target = resolve_sec_href(case["request_url"], url)
    parsed = urlsplit(target)
    if (
        parsed.scheme.lower() not in DEFAULT_ARCHIVE_URL_POLICY.allowed_schemes
        or (parsed.hostname or "").lower()
        not in DEFAULT_ARCHIVE_URL_POLICY.allowed_hosts
    ):
        return False
    try:
        has_port = parsed.port is not None
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None or has_port:
        return False
    if "%" in parsed.path or "\\" in parsed.path or "//" in parsed.path:
        return False
    decoded = [unquote(part) for part in parsed.path.split("/")]
    if any(part in {".", ".."} or "/" in part or "\\" in part for part in decoded):
        return False
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    data_index = next(
        (index for index, part in enumerate(parts) if part.lower() == "data"), None
    )
    if data_index is None or len(parts) <= data_index + 3:
        return False
    return parts[data_index + 2].removesuffix("-index.html") == case[
        "accession"
    ].replace("-", "")


def _matches_accession_bundle_path(url: str, case: dict) -> bool:
    target = resolve_sec_href(case["request_url"], url)
    parsed = urlsplit(target)
    if (
        parsed.scheme.lower() not in DEFAULT_ARCHIVE_URL_POLICY.allowed_schemes
        or (parsed.hostname or "").lower()
        not in DEFAULT_ARCHIVE_URL_POLICY.allowed_hosts
    ):
        return False
    try:
        has_port = parsed.port is not None
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None or has_port:
        return False
    if "%" in parsed.path or "\\" in parsed.path or "//" in parsed.path:
        return False
    decoded = [unquote(part) for part in parsed.path.split("/")]
    if any(part in {".", ".."} or "/" in part or "\\" in part for part in decoded):
        return False
    parts = [part for part in decoded if part]
    data_index = next(
        (index for index, part in enumerate(parts) if part.lower() == "data"), None
    )
    accession, leaf = _bundle_path_identity(parts, data_index)
    return accession == case["accession"].replace("-", "") and leaf.lower().endswith(
        ".txt"
    )


def _bundle_path_identity(
    parts: list[str], data_index: int | None
) -> tuple[str | None, str]:
    if data_index is None or len(parts) <= data_index + 2:
        return None, ""
    candidate = parts[data_index + 2]
    normalized = candidate.casefold()
    if normalized.endswith(".txt"):
        return normalized.removesuffix(".txt").replace("-", ""), candidate
    if len(parts) > data_index + 3:
        return candidate.replace("-", ""), parts[data_index + 3]
    return candidate, ""


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


def _row_path_kind(row: dict) -> str:
    url = (row.get("archive_url") or row.get("href") or "").strip()
    parsed = urlsplit(url)
    parts = [part.lower() for part in parsed.path.split("/") if part]
    extension = Path(parsed.path).suffix.lower()
    if any(part.startswith("xsl") for part in parts) and extension == ".xml":
        return "xsl_nested_xml"
    if extension == ".xml":
        return "flat_xml"
    if extension in {".htm", ".html"}:
        return "html"
    return "other"


def _source_archive_cik(request_url: str) -> str | None:
    parts = [unquote(part) for part in urlsplit(request_url).path.split("/") if part]
    data_index = next(
        (index for index, part in enumerate(parts) if part.lower() == "data"), None
    )
    if data_index is None or len(parts) <= data_index + 1:
        return None
    return parts[data_index + 1]


def _is_exhibit(document_type: str) -> bool:
    return document_type.startswith(_EXHIBIT_TYPES) or document_type in _EXHIBIT_NAMES


def _matches_form(document_type: str, form: str) -> bool:
    normalized_type = document_type.strip().upper()
    normalized_form = form.strip().upper()
    if normalized_type == normalized_form:
        return True
    family = resolve_alias(normalized_form)
    return family is not None and resolve_alias(normalized_type) == family


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_summary(row: dict) -> dict:
    return {
        field: row.get(field)
        for field in (
            "table_kind",
            "row_ordinal",
            "sequence",
            "document_type",
            "filename",
            "href",
            "archive_url",
        )
    }


def _finding(case: dict, code: str, **details) -> dict:
    return {
        "run_id": case.get("run_id"),
        "accession": case["accession"],
        "request_url": case["request_url"],
        "response_sha256": case["response_sha256"],
        "code": code,
        **details,
    }
