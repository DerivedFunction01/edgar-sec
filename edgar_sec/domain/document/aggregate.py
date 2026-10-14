"""SEC filing submission aggregate and attachment domain records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
import zipfile

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
    primary_document_url: str | None = None
    fetcher: Callable[[FilingAggregate], bytes | None] | None = None
    cache_clearer: Callable[[str], int] | None = None
    zip_exporter: Callable[[FilingAggregate, Path], Path] | None = None
    attachment_loader: (
        Callable[[FilingAggregate], tuple[FilingAttachment, ...]] | None
    ) = None

    @property
    def is_joint_filing(self) -> bool:
        return len(self.ciks) > 1

    def has_cik(self, cik: Cik | str | int) -> bool:
        target = cik if isinstance(cik, Cik) else Cik.from_raw(cik)
        return target in self.ciks

    def get_attachments(self) -> tuple[FilingAttachment, ...]:
        """Return all attachments, hydrating via loader if needed."""
        if self.attachments:
            return self.attachments
        if self.attachment_loader is not None:
            return self.attachment_loader(self)
        return ()

    @property
    def exhibits(self) -> tuple[FilingAttachment, ...]:
        return tuple(
            a
            for a in self.get_attachments()
            if a.document_type.upper().startswith("EX-")
        )

    def as_report(self) -> FormReport:
        from edgar_sec.domain.forms.reports import get_report_projection

        return get_report_projection(self)

    def raw(self) -> bytes | None:
        """Return raw bytes of the primary filing document."""
        if (
            self.primary_storage_path is not None
            and self.primary_storage_path.is_file()
        ):
            return self.primary_storage_path.read_bytes()
        if self.fetcher is not None:
            return self.fetcher(self)
        return None

    def save(self, destination: Path | str) -> Path:
        """Save primary document bytes to destination path."""
        data = self.raw()
        if data is None:
            raise FileNotFoundError(
                f"no primary document available for {self.accession}"
            )
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def to_zip(self, zip_path: Path | str) -> Path:
        """Export filing document to a ZIP archive."""
        target = Path(zip_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.zip_exporter is not None:
            return self.zip_exporter(self, target)
        data = self.raw()
        if data is None:
            raise FileNotFoundError(
                f"no document available to archive for {self.accession}"
            )
        fname = (
            Path(self.primary_document_path).name
            if self.primary_document_path
            else "primary_document.txt"
        )
        with zipfile.ZipFile(
            target, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(f"{self.accession.value}/{fname}", data)
        return target

    def clear_cache(self) -> int:
        """Clear cached documents for this accession."""
        if self.cache_clearer is not None:
            return self.cache_clearer(self.accession.value)
        return 0


__all__ = ["FilingAggregate", "FilingAttachment"]
