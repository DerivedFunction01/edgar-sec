"""SEC filing submission aggregate and attachment domain records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from edgar_sec.domain.identity import AccessionNumber, Cik

if TYPE_CHECKING:
    from edgar_sec.domain.forms.reports import FormReport


@dataclass(frozen=True, slots=True)
class FilingAttachment:
    """Attachment or exhibit record within a filing submission."""

    attachment_id: str
    document_type: str
    filename: str
    url: str
    size: int | None = None
    sha256: str | None = None
    description: str | None = None
    storage_path: Path | None = None


@dataclass(frozen=True, slots=True)
class FilingAggregate:
    """Universal domain aggregate root representing an SEC filing submission."""

    accession: AccessionNumber
    primary_cik: Cik
    ciks: tuple[Cik, ...]
    form: str
    filing_date: str
    report_date: str | None = None
    acceptance_datetime: str | None = None
    primary_document_path: str = ""
    primary_sha256: str | None = None
    primary_storage_path: Path | None = None
    attachments: tuple[FilingAttachment, ...] = ()
    run_id: str | None = None
    plan_id: str | None = None
    xbrl: Any | None = None

    @property
    def is_joint_filing(self) -> bool:
        return len(self.ciks) > 1

    def has_cik(self, cik: Cik | str | int) -> bool:
        target = cik if isinstance(cik, Cik) else Cik.from_raw(cik)
        return target in self.ciks

    @property
    def exhibits(self) -> tuple[FilingAttachment, ...]:
        return tuple(
            a for a in self.attachments if a.document_type.upper().startswith("EX-")
        )

    def as_report(self) -> FormReport:
        from edgar_sec.domain.forms.reports import get_report_projection

        return get_report_projection(self)


__all__ = ["FilingAggregate", "FilingAttachment"]
