"""Canonical attachment row and the single role derivation.

The row is the client-facing projection of a published inventory entry; both
client loaders hydrate attachments from it so identity is defined once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.document.aggregate import AttachmentRole, FilingAttachment
from edgar_sec.domain.document_inventory.models import InventoryEntry
from edgar_sec.domain.forms.common.aliases import resolve_alias


def _normalize_form(value: str) -> str:
    normalized = " ".join(value.split()).upper()
    return resolve_alias(normalized) or normalized


def attachment_role(
    table_kind: str | None,
    document_type: str | None,
    *,
    form: str,
) -> AttachmentRole | None:
    """Derive an entry's observed role; ``data_file`` needs the kind observed."""
    doc_type = (document_type or "").strip().upper()
    if table_kind == "data_file":
        return "data_file"
    if doc_type == "GRAPHIC" and table_kind != "data_file":
        return "graphic"
    if form and doc_type and _normalize_form(doc_type) == _normalize_form(form):
        return "primary"
    if doc_type.startswith("EX-"):
        return "exhibit"
    return None


@dataclass(frozen=True, slots=True)
class CanonicalAttachmentRow:
    """One attachment's identity fields, as observed by its source vehicle."""

    entry_id: str | None
    accession: str
    table_kind: str | None
    sequence: int | None
    document_type: str | None
    document_label: str | None
    description: str | None
    filename: str | None
    href: str | None
    archive_url: str | None
    byte_size: int | None
    payload_sha256: str | None = None

    @classmethod
    def from_inventory_entry(cls, entry: InventoryEntry) -> CanonicalAttachmentRow:
        """Project a published inventory entry into the canonical row."""
        return cls(
            entry_id=entry.entry_id,
            accession=str(entry.accession),
            table_kind=entry.table_kind,
            sequence=entry.sequence,
            document_type=entry.document_type,
            document_label=entry.document_label,
            description=entry.description,
            filename=entry.filename,
            href=entry.href,
            archive_url=entry.archive_url,
            byte_size=entry.byte_size,
        )

    @classmethod
    def from_attachment(
        cls, accession: str, attachment: FilingAttachment
    ) -> CanonicalAttachmentRow:
        """Rebuild the row a hydrated attachment was projected from."""
        return cls(
            entry_id=attachment.entry_id,
            accession=accession,
            table_kind=attachment.table_kind,
            sequence=attachment.sequence,
            document_type=attachment.document_type or None,
            document_label=None,
            description=attachment.description,
            filename=attachment.filename or None,
            href=None,
            archive_url=attachment.url or None,
            byte_size=attachment.size,
            payload_sha256=attachment.sha256,
        )

    def role(self, *, form: str) -> AttachmentRole | None:
        """Return this row's observed role within a filing of ``form``."""
        return attachment_role(self.table_kind, self.document_type, form=form)

    def to_attachment(
        self,
        *,
        form: str,
        fetcher: Callable[[FilingAttachment], bytes | None] | None = None,
        renderer: Callable[[FilingAttachment], str | bytes | None] | None = None,
        storage_path: Path | None = None,
    ) -> FilingAttachment:
        """Hydrate the in-memory attachment object from this row."""
        return FilingAttachment(
            attachment_id=self.entry_id or self.filename or "",
            document_type=self.document_type or "",
            filename=self.filename or "",
            url=self.archive_url or "",
            size=self.byte_size,
            sha256=self.payload_sha256,
            description=self.description,
            storage_path=storage_path,
            fetcher=fetcher,
            renderer=renderer,
            entry_id=self.entry_id,
            sequence=self.sequence,
            table_kind=self.table_kind,
            role=self.role(form=form),
        )


__all__ = [
    "CanonicalAttachmentRow",
    "attachment_role",
]
