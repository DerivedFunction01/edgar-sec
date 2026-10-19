"""Resolve profile requests against the selected immutable evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from edgar_sec.domain.document.path_facts import PLACEHOLDER_PRIMARY_FILENAMES
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import (
    SEC_ARCHIVE_BASE,
    archives_url,
    parse_archive_url,
    resolve_archive_href,
    validate_archive_url,
)
from edgar_sec.foundation.serialization import canonical_hash
from .catalog_scope import CatalogScopeAccession
from .inventory_evidence import InventoryEvidenceRow
from .profiles import ProfileTarget

_TARGET_STATUSES = {
    "matched",
    "not_filed",
    "required_missing",
    "ambiguous",
    "unresolved",
    "constructed_candidate",
}
_COMPLETE_SUBMISSION_NAME = re.compile(r"\d{10}-\d{2}-\d{6}\.txt$")
_NUMBERED_DOCUMENT_NAME = re.compile(r"\d{4}\.[A-Za-z0-9]+\Z", re.ASCII)


def _is_placeholder_primary_path(document_path: str | None) -> bool:
    """Match exact placeholder names without deciding retrieval eligibility."""
    if not document_path:
        return False
    path = urlsplit(document_path.strip()).path
    if _COMPLETE_SUBMISSION_NAME.fullmatch(path.lstrip("/")):
        return False
    return path in PLACEHOLDER_PRIMARY_FILENAMES or (
        path.startswith("/") and path[1:] in PLACEHOLDER_PRIMARY_FILENAMES
    )


class TargetMatchingError(ValueError):
    """Selected source evidence cannot be matched without unsafe assumptions."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    entry_id: str | None
    target_url: str | None
    retrieval_mode: str
    sequence: int | None
    byte_size: int | None
    status_reason: str | None = None
    canonical_path: str | None = None


def catalog_only_rows(
    plan_id: str,
    accession: CatalogScopeAccession,
    targets: tuple[ProfileTarget, ...],
) -> list[dict[str, Any]]:
    identity = str(AccessionNumber.from_any(accession.accession))
    catalog_urls: tuple[str, ...] = ()
    catalog_urls_loaded = False
    rows = []
    for target in targets:
        if not catalog_urls_loaded:
            catalog_urls = _catalog_primary_urls(accession, identity)
            catalog_urls_loaded = True
        url = next(iter(catalog_urls)) if catalog_urls else None
        placeholder_primary = (
            target.role == "primary"
            and not url
            and _catalog_has_placeholder_primary(accession)
        )
        if placeholder_primary:
            candidate = _Candidate(
                None,
                None,
                "none",
                None,
                None,
                "placeholder_primary_requires_bundle_sequence",
            )
        else:
            candidate = _Candidate(
                None, url, "direct_url" if url else "none", None, None
            )
        rows.append(
            _target_row(
                plan_id,
                identity,
                accession.form,
                accession.filing_date or "",
                accession.report_date,
                target,
                candidate,
                status="matched" if candidate.target_url else "unresolved",
                status_reason=(
                    candidate.status_reason
                    or (None if candidate.target_url else "no_usable_primary_path")
                ),
                source_origin="catalog_direct",
                availability="catalog_metadata",
            )
        )
    return rows


def _catalog_has_placeholder_primary(accession: CatalogScopeAccession) -> bool:
    for occurrence in accession.occurrences:
        primary = (occurrence.primary_document or "").strip()
        path = (occurrence.document_path or "").strip()
        if (
            primary
            and (not path or path == primary)
            and _is_placeholder_primary_path(path or primary)
        ):
            return True
    return False


def _catalog_primary_urls(
    accession: CatalogScopeAccession, canonical_accession: str
) -> tuple[str, ...]:
    candidates_by_path: dict[str, set[str]] = {}
    for occurrence in accession.occurrences:
        primary = (occurrence.primary_document or "").strip()
        document = (occurrence.document_path or "").strip()
        if not primary or (document and document.casefold() != primary.casefold()):
            continue
        path = document or primary
        numbered_path = _numbered_document_path(path)
        if _is_placeholder_primary_path(path) and numbered_path is None:
            continue
        expected_path = (
            _accession_numbered_document_path(canonical_accession, numbered_path)
            if numbered_path
            else path
        )
        url = occurrence.archive_url
        if url:
            safe = _validated_archive_url(url, canonical_accession)
            parsed = parse_archive_url(safe)
            if (
                parsed is None
                or parsed.document_path.casefold() != expected_path.casefold()
            ):
                raise TargetMatchingError(
                    f"catalog primary URL disagrees with its path for {canonical_accession}"
                )
        else:
            if not path or ".." in path.split("/") or "\\" in path:
                continue
            url = archives_url(
                occurrence.source_cik, canonical_accession, expected_path
            )
            safe = _validated_archive_url(
                url,
                canonical_accession,
                expected_archive_cik=occurrence.source_cik,
            )
        candidates_by_path.setdefault(expected_path.casefold(), set()).add(safe)
    if len(candidates_by_path) > 1:
        raise TargetMatchingError(
            f"conflicting catalog primary paths for {canonical_accession}"
        )
    if not candidates_by_path:
        return ()
    urls = next(iter(candidates_by_path.values()))
    return (sorted(urls)[0],)


def inventory_rows(
    plan_id: str,
    evidence_rows: list[InventoryEvidenceRow],
    targets: tuple[ProfileTarget, ...],
) -> list[dict[str, Any]]:
    first = evidence_rows[0]
    accession = first.accession
    rows: list[dict[str, Any]] = []
    for target in targets:
        if not first.indexed:
            rows.append(
                _target_row(
                    plan_id,
                    accession,
                    first.catalog_form,
                    first.catalog_filing_date,
                    first.catalog_report_date,
                    target,
                    _Candidate(None, None, "none", None, None),
                    status="unresolved",
                    status_reason="accession_not_indexed",
                    source_origin="inventory_index",
                    availability="none",
                )
            )
            continue
        accession_row = first.accession_row or {}
        if target.role == "package":
            rows.append(_package_row(plan_id, first, accession_row, target))
            continue
        candidates = [
            item.entry_row
            for item in evidence_rows
            if item.entry_row is not None
            and _matches_target(item.entry_row, target, first.catalog_form)
        ]
        candidates.sort(key=lambda item: str(item.get("entry_id") or ""))
        if not candidates:
            rows.append(
                _target_row(
                    plan_id,
                    accession,
                    first.catalog_form,
                    first.catalog_filing_date,
                    first.catalog_report_date,
                    target,
                    _Candidate(None, None, "none", None, None),
                    status="not_filed" if target.optional else "required_missing",
                    status_reason="no_matching_entry",
                    source_origin="inventory_index",
                    availability="index_html",
                )
            )
            continue
        ambiguous = len(candidates) > 1
        for entry in candidates:
            candidate = _entry_candidate(entry, accession_row, accession, target)
            if ambiguous:
                status = "ambiguous"
                reason = candidate.status_reason
            elif candidate.target_url is None:
                status = "unresolved"
                reason = candidate.status_reason or "no_usable_retrieval_locator"
            else:
                status = "matched"
                reason = None
            rows.append(
                _target_row(
                    plan_id,
                    accession,
                    first.catalog_form,
                    first.catalog_filing_date,
                    first.catalog_report_date,
                    target,
                    candidate,
                    status=status,
                    status_reason=reason,
                    source_origin="inventory_index",
                    availability="index_html",
                )
            )
    return rows


def _matches_target(entry: Mapping[str, Any], target: ProfileTarget, form: str) -> bool:
    table_kind = str(entry.get("table_kind") or "")
    document_type = str(entry.get("document_type") or "").strip().upper()
    if target.role == "primary":
        return table_kind == "document_format" and _normalize_form(
            document_type
        ) == _normalize_form(form)
    if target.role == "exhibit":
        return table_kind == "document_format" and _type_matches(
            document_type, target.type
        )
    if target.role == "data_file":
        if table_kind != "data_file":
            return False
        if target.type == "extracted_xbrl_instance":
            description = " ".join(str(entry.get("description") or "").split()).upper()
            return (
                description == "EXTRACTED XBRL INSTANCE DOCUMENT"
                and document_type == "XML"
            )
        return _type_matches(document_type, target.type)
    if target.role == "graphic":
        return table_kind == "document_format" and document_type == "GRAPHIC"
    return False


def _type_matches(value: str, requested: str) -> bool:
    normalized = value.strip().upper()
    requested = requested.upper()
    if requested.endswith("*"):
        return normalized.startswith(requested[:-1])
    return normalized == requested


def _normalize_form(value: str) -> str:
    normalized = " ".join(value.split()).upper()
    return resolve_alias(normalized) or normalized


def _entry_candidate(
    entry: Mapping[str, Any],
    accession_row: Mapping[str, Any],
    accession: str,
    target: ProfileTarget,
) -> _Candidate:
    entry_id = str(entry.get("entry_id") or "")
    if not entry_id:
        raise TargetMatchingError(f"inventory entry lacks identity for {accession}")
    archive_url = str(entry.get("archive_url") or "").strip()
    href = str(entry.get("href") or "").strip()
    bundle_url = str(accession_row.get("bundle_url") or "").strip()
    index_url = str(accession_row.get("index_url") or "").strip()
    reference_base = index_url or bundle_url
    directory_href = False
    filename = str(entry.get("filename") or "").strip()
    numbered_filename = _numbered_document_path(filename)
    numbered_locator_mismatch = False
    if target.role == "primary" and _is_placeholder_primary_path(filename):
        numbered_url = _numbered_accession_url(
            archive_url, filename, accession, reference_base or None
        )
        if numbered_url:
            size = entry.get("byte_size")
            return _Candidate(
                entry_id,
                numbered_url,
                "direct_url",
                None,
                size if isinstance(size, int) and not isinstance(size, bool) else None,
            )
        sequence = entry.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            return _Candidate(
                entry_id,
                None,
                "none",
                None,
                None,
                "placeholder_primary_missing_positive_sequence",
            )
        if not bundle_url:
            return _Candidate(
                entry_id,
                None,
                "none",
                None,
                None,
                "placeholder_primary_missing_bundle_url",
            )
        safe_bundle = _validated_bundle_url(bundle_url, accession)
        size = entry.get("byte_size")
        return _Candidate(
            entry_id,
            safe_bundle,
            "bundle_sequence",
            sequence,
            size if isinstance(size, int) and not isinstance(size, bool) else None,
            canonical_path=filename or None,
        )
    urls: list[str] = []
    for observed in (archive_url, href):
        if not observed:
            continue
        if observed == href and _is_directory_only_archive_locator(observed, accession):
            if archive_url:
                raise TargetMatchingError(
                    f"inventory archive_url and href disagree for {entry_id}"
                )
            directory_href = True
            continue
        resolved = observed
        if not urlsplit(observed).scheme:
            if not reference_base:
                raise TargetMatchingError(
                    f"relative inventory locator has no SEC URL base for {accession}"
                )
        safe_url = _validated_archive_url(
            resolved,
            accession,
            base_url=reference_base or None,
        )
        if numbered_filename and not _has_accession_numbered_leaf(
            safe_url, accession, numbered_filename
        ):
            numbered_locator_mismatch = True
            continue
        urls.append(safe_url)
    if urls:
        distinct = set(urls)
        if len(distinct) != 1 or numbered_locator_mismatch:
            raise TargetMatchingError(
                f"inventory archive_url and href disagree for {entry_id}"
            )
        size = entry.get("byte_size")
        return _Candidate(
            entry_id,
            urls[0],
            "direct_url",
            None,
            size if isinstance(size, int) and not isinstance(size, bool) else None,
        )
    if (archive_url or (href and not directory_href)) and not numbered_locator_mismatch:
        raise TargetMatchingError(f"unsafe inventory locator for {entry_id}")
    sequence = entry.get("sequence")
    if target.role == "exhibit" and sequence is not None and bundle_url:
        safe_bundle = _validated_bundle_url(bundle_url, accession)
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise TargetMatchingError(f"invalid bundle sequence for {entry_id}")
        size = entry.get("byte_size")
        return _Candidate(
            entry_id,
            safe_bundle,
            "bundle_sequence",
            sequence,
            size if isinstance(size, int) and not isinstance(size, bool) else None,
            canonical_path=filename or None,
        )
    return _Candidate(entry_id, None, "none", None, None, "no_usable_retrieval_locator")


def _numbered_document_path(path: str | None) -> str | None:
    if not path or not _NUMBERED_DOCUMENT_NAME.fullmatch(path):
        return None
    return path if int(path[:4]) > 0 else None


def _accession_numbered_document_path(accession: str, filename: str) -> str:
    return f"{AccessionNumber.from_any(accession)}-{filename}"


def _has_accession_numbered_leaf(url: str, accession: str, filename: str) -> bool:
    parsed = parse_archive_url(url)
    expected = _accession_numbered_document_path(accession, filename)
    return parsed is not None and parsed.document_path.casefold() == expected.casefold()


def _numbered_accession_url(
    url: str,
    filename: str,
    accession: str,
    base_url: str | None,
) -> str | None:
    numbered_filename = _numbered_document_path(filename)
    if not url or not numbered_filename:
        return None
    safe = _validated_archive_url(url, accession, base_url=base_url)
    return (
        safe
        if _has_accession_numbered_leaf(safe, accession, numbered_filename)
        else None
    )


def _is_directory_only_archive_locator(locator: str, accession: str) -> bool:
    try:
        parts = urlsplit(locator)
        port = parts.port
    except ValueError:
        return False
    if (
        parts.query
        or parts.fragment
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or (parts.scheme and parts.scheme.casefold() != "https")
        or (parts.netloc and parts.hostname != urlsplit(SEC_ARCHIVE_BASE).hostname)
        or (not parts.scheme and parts.netloc)
    ):
        return False
    path = parts.path
    if not path.startswith("/") or any(char in path for char in ("%", "\\")):
        return False
    if "//" in path or any(segment in {".", ".."} for segment in path.split("/")):
        return False
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) == 4:
        return segments[:3] == ["Archives", "edgar", "data"] and segments[3].isdigit()
    if len(segments) != 5 or segments[:3] != ["Archives", "edgar", "data"]:
        return False
    return (
        segments[3].isdigit()
        and segments[4] == AccessionNumber.from_any(accession).normalized
    )


def _package_row(
    plan_id: str,
    evidence: InventoryEvidenceRow,
    accession_row: Mapping[str, Any],
    target: ProfileTarget,
) -> dict[str, Any]:
    accession = evidence.accession
    bundle_url = str(accession_row.get("bundle_url") or "").strip()
    if not bundle_url:
        candidate = _Candidate(None, None, "none", None, None)
        status = "unresolved"
        reason = "no_usable_bundle_url"
        availability = "none"
    else:
        safe_bundle = _validated_bundle_url(bundle_url, accession)
        parsed = urlsplit(safe_bundle)
        if not parsed.path.endswith(".txt"):
            raise TargetMatchingError(
                f"inventory bundle URL is not a .txt filing: {accession}"
            )
        candidate = _Candidate(
            None,
            urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path[:-4] + "-xbrl.zip", "", "")
            ),
            "constructed_package",
            None,
            None,
        )
        status = "constructed_candidate"
        reason = "constructed_not_verified"
        availability = "constructed"
    return _target_row(
        plan_id,
        accession,
        evidence.catalog_form,
        evidence.catalog_filing_date,
        evidence.catalog_report_date,
        target,
        candidate,
        status=status,
        status_reason=reason,
        source_origin="inventory_index",
        availability=availability,
    )


def _validated_bundle_url(url: str, accession: str) -> str:
    validated = _validated_archive_url(url, accession)
    parsed = parse_archive_url(validated)
    if parsed is None or not parsed.document_path.endswith(".txt"):
        raise TargetMatchingError(f"unsafe accession bundle URL for {accession}")
    return validated


def _validated_archive_url(
    url: str,
    accession: str,
    *,
    base_url: str | None = None,
    expected_archive_cik: object | None = None,
) -> str:
    try:
        if base_url is not None:
            return resolve_archive_href(
                base_url,
                url,
                accession,
                expected_archive_cik=expected_archive_cik,
            ).url
        return validate_archive_url(
            url, accession, expected_archive_cik=expected_archive_cik
        ).url
    except ValueError as error:
        if "outside the expected accession" in str(error):
            raise TargetMatchingError(
                f"SEC archive URL is outside accession {accession}"
            ) from error
        raise TargetMatchingError(f"unsafe SEC archive URL: {url!r}") from error


def _target_row(
    plan_id: str,
    accession: str,
    form: str,
    filing_date: str,
    report_date: str | None,
    target: ProfileTarget,
    candidate: _Candidate,
    *,
    status: str,
    status_reason: str | None,
    source_origin: str,
    availability: str,
) -> dict[str, Any]:
    if status not in _TARGET_STATUSES:
        raise TargetMatchingError(f"invalid target status: {status!r}")
    identity = [plan_id, accession, target.request_id, candidate.entry_id, status]
    canonical_path = candidate.canonical_path
    if canonical_path is None and candidate.target_url:
        parsed = parse_archive_url(candidate.target_url)
        canonical_path = parsed.document_path if parsed is not None else None
    return {
        "target_id": canonical_hash(identity),
        "accession": accession,
        "form": form,
        "filing_date": filing_date,
        "report_date": report_date,
        "request_id": target.request_id,
        "target_role": target.role,
        "target_type": target.type,
        "optional": target.optional,
        "inventory_entry_id": candidate.entry_id,
        "status": status,
        "status_reason": status_reason,
        "source_origin": source_origin,
        "retrieval_mode": candidate.retrieval_mode,
        "target_url": candidate.target_url,
        "sequence": candidate.sequence,
        "byte_size": candidate.byte_size,
        "availability_evidence": availability,
        "catalog_direct_selection": (
            target.catalog_direct_selection
            if source_origin == "catalog_direct"
            else None
        ),
        "_canonical_path": canonical_path,
        "_requested_operations": (
            [operation.value for operation in target.acquisition_policy.operations]
            if target.acquisition_policy is not None
            else None
        ),
    }


__all__ = [
    "TargetMatchingError",
    "catalog_only_rows",
    "inventory_rows",
]
