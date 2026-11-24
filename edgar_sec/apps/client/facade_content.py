"""Document-content surface of the Edgar facade: sections, notes, TOC, tables."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from edgar_sec.apps.client.caching.content_cache import estimate_retained_bytes

if TYPE_CHECKING:
    from edgar_sec.domain.document.aggregate import FilingAggregate
    from edgar_sec.engine.forms.cover.toc.models import TocSpan
    from edgar_sec.engine.forms.sections.models import (
        NotesSequence,
        SectionSequence,
    )


class ContentMixin:
    """Document-content methods composed into the Edgar facade."""

    def sections(
        self, filing: FilingAggregate, text: str | None = None
    ) -> SectionSequence:
        """Detect and return full statutory Part/Item section sequence."""
        from edgar_sec.engine.forms.sections.models import SectionSequence

        if not filing.has_sections:
            return SectionSequence(sections=(), family=filing.form)

        if text is not None:
            return self._detect_sections(filing, text)
        return self.content_cache.get_or_build(
            ("sections", filing.accession.value),
            lambda: self._build_sections(filing),
        )

    def _build_sections(self, filing: FilingAggregate) -> tuple[SectionSequence, int]:
        body = self._extract_filing_text(filing)
        seq = self._detect_sections(filing, body)
        return seq, estimate_retained_bytes(seq) if body else 0

    def _detect_sections(self, filing: FilingAggregate, body: str) -> SectionSequence:
        from edgar_sec.apps.client.core.section_detection import detect_sections

        return detect_sections(filing, body)

    def section(
        self, filing: FilingAggregate, item: str, text: str | None = None
    ) -> str:
        """Extract and return text of a specific section (e.g. 'ITEM 1A')."""
        if not filing.has_sections:
            return ""
        body = text if text is not None else self._extract_filing_text(filing)
        if not body:
            return ""
        seq = self.sections(filing, text=body)
        return seq.get_text(body, item)

    def notes(self, filing: FilingAggregate, text: str | None = None) -> NotesSequence:
        """Detect and return financial statement footnotes."""
        from edgar_sec.engine.forms.sections.models import NotesSequence

        if not filing.has_notes:
            return NotesSequence(notes=())

        if text is not None:
            return self._detect_notes(filing, text)
        return self.content_cache.get_or_build(
            ("notes", filing.accession.value),
            lambda: self._build_notes(filing),
        )

    def _build_notes(self, filing: FilingAggregate) -> tuple[NotesSequence, int]:
        body = self._extract_filing_text(filing)
        seq = self._detect_notes(filing, body)
        return seq, estimate_retained_bytes(seq) if body else 0

    def _detect_notes(self, filing: FilingAggregate, body: str) -> NotesSequence:
        from edgar_sec.domain.forms.common.processing import profile_version_of
        from edgar_sec.domain.forms.families.processing_profiles import (
            get_family_profile,
        )
        from edgar_sec.engine.forms.sections.models import NotesSequence
        from edgar_sec.engine.forms.sections.notes.detector import (
            detect_notes_sequence,
        )

        if not body:
            return NotesSequence(notes=())

        return detect_notes_sequence(
            body,
            renderer_version=profile_version_of(get_family_profile(filing.form)),
        )

    def note(
        self,
        filing: FilingAggregate,
        number: int | str,
        text: str | None = None,
    ) -> str:
        """Extract and return clean text of a specific financial note."""
        if not filing.has_notes:
            return ""
        body = text if text is not None else self._extract_filing_text(filing)
        if not body:
            return ""
        seq = self.notes(filing, text=body)
        try:
            num = (
                int(number)
                if isinstance(number, int)
                else int("".join(c for c in str(number) if c.isdigit()))
            )
        except (ValueError, TypeError):
            return ""
        return seq.get_text(body, num)

    def toc(self, filing: FilingAggregate, text: str | None = None) -> TocSpan | None:
        """Return detected Table of Contents span if present."""
        if not filing.has_toc:
            return None
        body = text if text is not None else self._extract_filing_text(filing)
        from edgar_sec.apps.client.core.section_detection import detect_toc_span

        return detect_toc_span(filing, body)

    def classified_tables(
        self, filing: FilingAggregate, *, stratum: str | None = None
    ) -> tuple["ClassifiedTable", ...]:
        """Classify one filing's free-text tables on demand (fast version).

        The pipeline version over the published store serves many filings;
        this one computes a single filing in the call, cached.
        """
        from edgar_sec.apps.client.documents.classified_tables import (
            ClassifiedTable,
            classified_tables_fast,
        )

        return classified_tables_fast(self.content_cache, filing, stratum=stratum)

    def classified_tables_from_store(
        self, filing: FilingAggregate, *, store_root: Path | str | None = None
    ) -> "PipelineClassifiedTables":
        """Serve one filing's classified tables from the published store.

        The pipeline version (D2): read-only over the published store,
        honest absence when missing; never a compute fallback.
        """
        from edgar_sec.apps.client.documents.classified_tables_pipeline import (
            PipelineClassifiedTables,
            classified_tables_pipeline,
        )

        return classified_tables_pipeline(
            filing, store_root=store_root, artifacts_root=self.artifacts_root
        )

    def _extract_filing_text(self, filing: FilingAggregate) -> str:
        return self.content_cache.get_or_build(
            ("text", filing.accession.value),
            lambda: self._read_filing_text(filing),
        )

    def _read_filing_text(self, filing: FilingAggregate) -> tuple[str, int]:
        from edgar_sec.domain.forms.reports import CompanyReport

        report = filing.as_report()
        if isinstance(report, CompanyReport):
            text = report.text() or ""
            return text, len(text)
        return "", 0
