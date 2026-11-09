"""Per-filing attachment collection with typed selectors.

Selectors return the same objects the collection enumerates and never
fetch; acquisition state and content access are separate surfaces.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from edgar_sec.domain.document.aggregate import (
    AttachmentRole,
    FilingAttachment,
    is_exhibit_attachment,
)


def _exhibit_type_matches(document_type: str, filter_types: set[str]) -> bool:
    canon_dt = document_type.upper()
    for ft in filter_types:
        canon_ft = f"EX-{ft}" if not ft.startswith("EX-") else ft
        if (
            canon_dt == canon_ft
            or canon_dt == ft
            or canon_dt.startswith(f"{canon_ft}.")
        ):
            return True
    return False


@dataclass(frozen=True, slots=True)
class Attachments:
    """One filing's attachments, in inventory order."""

    items: tuple[FilingAttachment, ...] = ()

    def __iter__(self) -> Iterator[FilingAttachment]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def by_role(self, role: AttachmentRole) -> Attachments:
        """Return the attachments whose observed role is ``role``."""
        return Attachments(tuple(a for a in self.items if a.role == role))

    def exhibits(self, types: Sequence[str] | str = ()) -> Attachments:
        """Return the exhibit attachments, optionally filtered by type."""
        filter_types = (
            {types.upper()}
            if isinstance(types, str) and types
            else {t.upper() for t in types}
            if types
            else None
        )
        return Attachments(
            tuple(
                a
                for a in self.items
                if is_exhibit_attachment(a.document_type, a.filename)
                and (
                    filter_types is None
                    or _exhibit_type_matches(a.document_type, filter_types)
                )
            )
        )

    def exhibit(self, type_or_number: str | int) -> FilingAttachment | None:
        """Safe exhibit retrieval by document type, number, or filename token."""
        token = str(type_or_number).upper().strip()
        canon_ex = f"EX-{token}" if not token.startswith("EX-") else token
        exhibits = self.exhibits().items
        for a in exhibits:
            dt = a.document_type.upper()
            if dt == canon_ex or dt == token:
                return a
        for a in exhibits:
            dt = a.document_type.upper()
            if dt.startswith(f"{canon_ex}.") or dt.startswith(f"{canon_ex}-"):
                return a
        for a in exhibits:
            fn = a.filename.lower()
            if token.lower() in fn or canon_ex.lower() in fn:
                return a
        return None

    def by_type(self, document_type: str) -> Attachments:
        """Return the attachments with exactly this document type."""
        target = document_type.upper()
        return Attachments(
            tuple(a for a in self.items if a.document_type.upper() == target)
        )

    def by_filename(self, filename: str) -> Attachments:
        """Return the attachments with exactly this filename."""
        target = filename.lower()
        return Attachments(tuple(a for a in self.items if a.filename.lower() == target))

    def by_sequence(self, sequence: int) -> Attachments:
        """Return the attachments observed at this index sequence."""
        return Attachments(tuple(a for a in self.items if a.sequence == sequence))

    def graphics(self) -> Attachments:
        """Return the graphic attachments."""
        return Attachments(tuple(a for a in self.items if a.is_graphic))

    def primary(self) -> Attachments:
        """Return the attachments in the primary role."""
        return self.by_role("primary")


__all__ = ["Attachments"]
