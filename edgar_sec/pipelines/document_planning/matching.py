"""Resolve profile requests against the selected immutable evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import (
    archives_url,
    parse_archive_url,
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


def catalog_only_rows(
    plan_id: str,
    accession: CatalogScopeAccession,
    targets: tuple[ProfileTarget, ...],
) -> list[dict[str, Any]]:
    identity = str(AccessionNumber.from_any(accession.accession))
    urls = _catalog_primary_urls(accession, identity)
    url = next(iter(urls)) if urls else None
    rows = []
    for target in targets:
        candidate = _Candidate(None, url, "direct_url" if url else "none", None, None)
        rows.append(
            _target_row(
                plan_id,
                identity,
                accession.form,
                accession.filing_date or "",
                target,
                candidate,
                status="matched" if url else "unresolved",
                status_reason=None if url else "no_usable_primary_path",
                source_origin="catalog_direct",
                availability="catalog_metadata",
            )
        )
    return rows


def _catalog_primary_urls(
    accession: CatalogScopeAccession, canonical_accession: str
) -> tuple[str, ...]:
    candidates: set[str] = set()
    for occurrence in accession.occurrences:
        primary = (occurrence.primary_document or "").strip()
        document = (occurrence.document_path or "").strip()
        if not primary or (document and document.casefold() != primary.casefold()):
            continue
        path = document or primary
        url = occurrence.archive_url
        if url:
            safe = _validated_archive_url(url, canonical_accession)
            parsed = parse_archive_url(safe)
            if parsed is None or parsed.document_path.casefold() != path.casefold():
                raise TargetMatchingError(
                    f"catalog primary URL disagrees with its path for {canonical_accession}"
                )
        else:
            if not path or ".." in path.split("/") or "\\" in path:
                continue
            url = archives_url(occurrence.source_cik, canonical_accession, path)
            safe = _validated_archive_url(
                url, canonical_accession, occurrence.source_cik
            )
        candidates.add(safe)
    if len(candidates) > 1:
        raise TargetMatchingError(
            f"conflicting catalog primary paths for {canonical_accession}"
        )
    return tuple(sorted(candidates))


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
                reason = "no_usable_retrieval_locator"
            else:
                status = "matched"
                reason = None
            rows.append(
                _target_row(
                    plan_id,
                    accession,
                    first.catalog_form,
                    first.catalog_filing_date,
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
    expected_archive_cik = _expected_archive_cik(accession_row, accession)
    archive_url = str(entry.get("archive_url") or "").strip()
    href = str(entry.get("href") or "").strip()
    bundle_url = str(accession_row.get("bundle_url") or "").strip()
    urls: list[str] = []
    for observed in (archive_url, href):
        if not observed:
            continue
        resolved = observed
        if not urlsplit(observed).scheme:
            if not bundle_url:
                raise TargetMatchingError(
                    f"relative inventory locator has no bundle URL for {accession}"
                )
            safe_bundle = _validated_bundle_url(
                bundle_url, accession, expected_archive_cik
            )
            resolved = urljoin(safe_bundle, observed)
        urls.append(_validated_archive_url(resolved, accession, expected_archive_cik))
    if urls:
        distinct = set(urls)
        if len(distinct) != 1:
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
    if archive_url or href:
        raise TargetMatchingError(f"unsafe inventory locator for {entry_id}")
    sequence = entry.get("sequence")
    if target.role == "exhibit" and sequence is not None and bundle_url:
        safe_bundle = _validated_bundle_url(
            bundle_url, accession, accession_row.get("filing_cik")
        )
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise TargetMatchingError(f"invalid bundle sequence for {entry_id}")
        size = entry.get("byte_size")
        return _Candidate(
            entry_id,
            safe_bundle,
            "bundle_sequence",
            sequence,
            size if isinstance(size, int) and not isinstance(size, bool) else None,
        )
    return _Candidate(entry_id, None, "none", None, None, "no_usable_retrieval_locator")


def _package_row(
    plan_id: str,
    evidence: InventoryEvidenceRow,
    accession_row: Mapping[str, Any],
    target: ProfileTarget,
) -> dict[str, Any]:
    accession = evidence.accession
    bundle_url = str(accession_row.get("bundle_url") or "").strip()
    expected_archive_cik = _expected_archive_cik(accession_row, accession)
    if not bundle_url:
        candidate = _Candidate(None, None, "none", None, None)
        status = "unresolved"
        reason = "no_usable_bundle_url"
        availability = "none"
    else:
        safe_bundle = _validated_bundle_url(bundle_url, accession, expected_archive_cik)
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
        target,
        candidate,
        status=status,
        status_reason=reason,
        source_origin="inventory_index",
        availability=availability,
    )


def _validated_bundle_url(
    url: str, accession: str, expected_archive_cik: object | None = None
) -> str:
    validated = _validated_archive_url(url, accession, expected_archive_cik)
    parsed = parse_archive_url(validated)
    if parsed is None or not parsed.document_path.endswith(".txt"):
        raise TargetMatchingError(f"unsafe accession bundle URL for {accession}")
    return validated


def _expected_archive_cik(
    accession_row: Mapping[str, Any], accession: str
) -> str | None:
    index_url = accession_row.get("index_url")
    if not index_url:
        return None
    try:
        return validate_archive_url(str(index_url), accession).archive_cik
    except ValueError as error:
        raise TargetMatchingError(
            f"unsafe SEC index URL for accession {accession}"
        ) from error


def _validated_archive_url(
    url: str, accession: str, expected_archive_cik: object | None = None
) -> str:
    try:
        return validate_archive_url(
            url, accession, expected_archive_cik=expected_archive_cik
        ).url
    except ValueError as error:
        if "outside the expected accession" in str(error):
            raise TargetMatchingError(
                f"SEC archive URL is outside accession {accession}"
            ) from error
        if "wrong archive CIK" in str(error):
            raise TargetMatchingError(
                f"SEC archive URL has the wrong CIK for {accession}"
            ) from error
        raise TargetMatchingError(f"unsafe SEC archive URL: {url!r}") from error


def _target_row(
    plan_id: str,
    accession: str,
    form: str,
    filing_date: str,
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
    return {
        "target_id": canonical_hash(identity),
        "accession": accession,
        "form": form,
        "filing_date": filing_date,
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
    }


__all__ = [
    "TargetMatchingError",
    "catalog_only_rows",
    "inventory_rows",
]
