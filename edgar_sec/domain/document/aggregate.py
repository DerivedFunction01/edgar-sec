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
    fetcher: Callable[[FilingAttachment], bytes | None] | None = None
    renderer: Callable[[FilingAttachment], str | bytes | None] | None = None

    @property
    def is_graphic(self) -> bool:
        doc_type = self.document_type.upper()
        if doc_type == "GRAPHIC":
            return True
        return self.filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp"))

    @property
    def is_xml(self) -> bool:
        return self.filename.lower().endswith((".xml", ".xsd"))

    def raw(self) -> bytes | None:
        """Return raw bytes of this attachment."""
        if self.storage_path is not None and self.storage_path.is_file():
            return self.storage_path.read_bytes()
        if self.fetcher is not None:
            return self.fetcher(self)
        return None

    def text(self) -> str | None:
        """Return text representation if attachment is not binary."""
        if self.is_graphic:
            return None
        data = self.raw()
        if data is not None:
            return data.decode("utf-8", errors="replace")
        return None

    def render(self) -> str | bytes | None:
        """Render attachment through configured renderer or fallback to text/raw."""
        if self.renderer is not None:
            return self.renderer(self)
        if self.is_graphic:
            return self.raw()
        return self.text()

    def save(self, destination: Path | str) -> Path:
        """Save attachment bytes to destination path."""
        data = self.raw()
        if data is None:
            raise FileNotFoundError(f"no payload available for {self.filename}")
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target


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
    document_opener: Callable[[FilingAggregate, str], bytes | None] | None = None
    bundle_fetcher: Callable[[FilingAggregate], bytes | None] | None = None
    index_fetcher: Callable[[FilingAggregate], str | None] | None = None
    renderer: Callable[[FilingAggregate], str | bytes | None] | None = None

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

    @property
    def graphics(self) -> tuple[FilingAttachment, ...]:
        """Return all graphic attachments."""
        return tuple(a for a in self.get_attachments() if a.is_graphic)

    @property
    def linkbases(self) -> tuple[FilingAttachment, ...]:
        """Return all discovered XBRL linkbase, schema, and instance attachments."""
        return tuple(
            a
            for a in self.get_attachments()
            if a.document_type.upper().startswith("EX-101")
            or a.filename.lower().endswith(
                (
                    "_cal.xml",
                    "_pre.xml",
                    "_def.xml",
                    "_lab.xml",
                    ".xsd",
                    "_htm.xml",
                    "-xbrl.zip",
                    "_xbrl.zip",
                )
            )
        )

    def open_linkbase(self, suffix_or_type: str) -> bytes:
        """Fetch and return bytes of a linkbase document by suffix or type."""
        token = suffix_or_type.lower().strip()
        for a in self.linkbases:
            if token in a.filename.lower() or token in a.document_type.lower():
                data = a.raw()
                if data is not None:
                    return data
        raise FileNotFoundError(
            f"linkbase {suffix_or_type!r} not found for {self.accession}"
        )

    def open_document(self, filename: str) -> bytes:
        """Fetch and return bytes of an arbitrary document within the accession."""
        if self.document_opener is not None:
            data = self.document_opener(self, filename)
            if data is not None:
                return data
        raise FileNotFoundError(
            f"document {filename!r} not available for {self.accession}"
        )

    def full_submission_bundle(self) -> bytes:
        """Fetch and return the complete SGML submission .txt bundle."""
        if self.bundle_fetcher is not None:
            data = self.bundle_fetcher(self)
            if data is not None:
                return data
        raise FileNotFoundError(
            f"full submission bundle not available for {self.accession}"
        )

    def save_bundle(self, destination: Path | str) -> Path:
        """Save the full submission bundle to destination path."""
        data = self.full_submission_bundle()
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def index_page(self) -> str:
        """Fetch and return the filing index HTML page."""
        if self.index_fetcher is not None:
            content = self.index_fetcher(self)
            if content is not None:
                return content
        raise FileNotFoundError(f"index page not available for {self.accession}")

    def render(self) -> str | bytes | None:
        """Render filing using injected renderer or raw primary bytes."""
        if self.renderer is not None:
            return self.renderer(self)
        return self.raw()


__all__ = ["FilingAggregate", "FilingAttachment"]
