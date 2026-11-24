from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from edgar_sec.domain.sec_urls import (
    DEFAULT_ARCHIVE_URL_POLICY,
    resolve_sec_href,
)


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


def _source_archive_cik(request_url: str) -> str | None:
    parts = [unquote(part) for part in urlsplit(request_url).path.split("/") if part]
    data_index = next(
        (index for index, part in enumerate(parts) if part.lower() == "data"), None
    )
    if data_index is None or len(parts) <= data_index + 1:
        return None
    return parts[data_index + 1]


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
