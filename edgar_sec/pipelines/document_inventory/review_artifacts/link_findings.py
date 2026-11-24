from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from edgar_sec.domain.sec_urls import (
    DEFAULT_ARCHIVE_URL_POLICY,
    resolve_sec_href,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.archive_paths import (
    _bundle_path_identity,
    _matches_accession_archive_path,
    _matches_accession_bundle_path,
    _source_archive_cik,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.records import (
    _finding,
    _row_summary,
)


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
