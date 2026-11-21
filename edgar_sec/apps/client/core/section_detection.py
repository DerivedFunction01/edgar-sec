"""The facade layer's one section-sequence derivation.

The Edgar facade and the Arrow sections builder both consume this
derivation; neither re-derives sections or the TOC span itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edgar_sec.domain.document.aggregate import FilingAggregate
    from edgar_sec.engine.forms.cover.toc.models import TocSpan
    from edgar_sec.engine.forms.sections.models import SectionSequence


def detect_toc_span(filing: FilingAggregate, body: str) -> TocSpan | None:
    """The filing's TOC span in ``body``, when its form supports one."""
    if not filing.has_toc or not body:
        return None
    from edgar_sec.engine.forms.cover.toc.finder import find_toc_span

    return find_toc_span(body)


def detect_sections(filing: FilingAggregate, body: str) -> SectionSequence:
    """Detect the Part/Item section sequence of one filing body."""
    from edgar_sec.engine.forms.sections.models import SectionSequence

    if not body:
        return SectionSequence(sections=(), family=filing.form)

    from edgar_sec.domain.forms.common.aliases import resolve_alias
    from edgar_sec.domain.forms.common.processing import profile_version_of
    from edgar_sec.domain.forms.families.processing_profiles import (
        get_family_entry,
    )
    from edgar_sec.engine.forms.sections.items.detector import (
        detect_section_sequence,
    )

    family = resolve_alias(filing.form) or filing.form.strip().upper()
    entry = get_family_entry(family)
    taxonomy = entry.taxonomy_items if entry is not None else ()
    toc_info = (
        detect_toc_span(filing, body) if entry and entry.profile.has_toc else None
    )
    toc_span = (
        (toc_info.start_line, toc_info.end_line) if toc_info is not None else None
    )
    return detect_section_sequence(
        body,
        family=family,
        taxonomy_items=taxonomy,
        toc_span=toc_span,
        renderer_version=profile_version_of(
            entry.profile if entry is not None else None
        ),
    )


__all__ = ["detect_sections", "detect_toc_span"]
