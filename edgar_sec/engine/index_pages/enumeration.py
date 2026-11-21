"""Resolve non-primary target intents against a parsed filing index page."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.document_inventory.models import (
    InventoryEntry,
    ParsedIndexPage,
)

_NON_PRIMARY_ROLES = {"exhibit", "data_file", "graphic"}


@dataclass(frozen=True, slots=True)
class TargetIntent:
    """One non-primary document request, in profile target vocabulary."""

    role: str
    type: str
    optional: bool
    request_id: str


@dataclass(frozen=True, slots=True)
class EnumeratedTarget:
    """The resolution of one intent against one filing's index page."""

    request_id: str
    role: str
    type: str
    document_type: str | None
    entry_id: str | None
    filename: str | None
    target_url: str | None
    sequence: int | None
    byte_size: int | None
    status: str
    status_reason: str | None


def enumerate_index_targets(
    page: ParsedIndexPage,
    intents: tuple[TargetIntent, ...],
) -> tuple[EnumeratedTarget, ...]:
    """Resolve each intent to index entries; never fabricate a candidate."""
    resolutions: list[EnumeratedTarget] = []
    for intent in intents:
        if intent.role not in _NON_PRIMARY_ROLES:
            raise ValueError(
                f"index enumeration covers non-primary intents only: {intent.role!r}"
            )
        candidates = [entry for entry in page.entries if _matches(entry, intent)]
        candidates.sort(key=lambda entry: entry.entry_id)
        if not candidates:
            resolutions.append(
                EnumeratedTarget(
                    request_id=intent.request_id,
                    role=intent.role,
                    type=intent.type,
                    document_type=None,
                    entry_id=None,
                    filename=None,
                    target_url=None,
                    sequence=None,
                    byte_size=None,
                    status="not_filed" if intent.optional else "required_missing",
                    status_reason="no_matching_entry",
                )
            )
            continue
        ambiguous = len(candidates) > 1
        for entry in candidates:
            if ambiguous:
                status, reason = "ambiguous", "multiple_matching_entries"
            elif entry.archive_url:
                status, reason = "matched", None
            else:
                status, reason = "unresolved", "no_usable_retrieval_locator"
            resolutions.append(
                EnumeratedTarget(
                    request_id=intent.request_id,
                    role=intent.role,
                    type=intent.type,
                    document_type=entry.document_type,
                    entry_id=entry.entry_id,
                    filename=entry.filename,
                    target_url=entry.archive_url,
                    sequence=entry.sequence,
                    byte_size=entry.byte_size,
                    status=status,
                    status_reason=reason,
                )
            )
    return tuple(resolutions)


def _matches(entry: InventoryEntry, intent: TargetIntent) -> bool:
    document_type = (entry.document_type or "").strip().upper()
    if intent.role == "exhibit":
        return entry.table_kind == "document_format" and _type_matches(
            document_type, intent.type
        )
    if intent.role == "data_file":
        if entry.table_kind != "data_file":
            return False
        if intent.type == "extracted_xbrl_instance":
            description = " ".join((entry.description or "").split()).upper()
            return (
                description == "EXTRACTED XBRL INSTANCE DOCUMENT"
                and document_type == "XML"
            )
        return _type_matches(document_type, intent.type)
    return entry.table_kind == "document_format" and document_type == "GRAPHIC"


def _type_matches(value: str, requested: str) -> bool:
    requested = requested.upper()
    if requested.endswith("*"):
        return value.startswith(requested[:-1])
    return value == requested


__all__ = ["EnumeratedTarget", "TargetIntent", "enumerate_index_targets"]
