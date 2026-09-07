"""String-first HTML document normalization pipeline."""

from __future__ import annotations

from collections.abc import Callable

from .cleaner import clean_html_for_parsing
from .decompose import decompose_html_structures


def normalize_html_document(
    html: str,
    *,
    cleanup_tables: Callable[[str], str] | None = None,
) -> str:
    """Render an HTML document into normalized text without tree text extraction.

    Tables are rendered while the surrounding HTML remains serialized so the
    structural decomposer can preserve paragraph cohesion. Rendered tagged
    tables remain protected by :func:`decompose_html_structures`. The table
    cleanup pass is deliberately retained as an explicit stage even though its
    current implementation is a no-op; a later false/layout-table pass can be
    added without changing callers or losing its position in the pipeline.

    ``cleanup_tables`` is injectable for focused tests and future policy
    experiments. Production callers use the shared ``cleanup_false_tables``
    implementation when omitted.
    """
    if not html:
        return ""

    if cleanup_tables is None:
        from defs.tables import cleanup_false_tables

        cleanup_tables = cleanup_false_tables

    from defs.tables import convert_html_tables_to_ascii
    from defs.tables.hybrid import normalize_hybrid_pre_text, restore_hybrid_pre_text

    cleaned = clean_html_for_parsing(html)
    hybrid = normalize_hybrid_pre_text(cleaned)
    rendered = convert_html_tables_to_ascii(hybrid.text, convert_to_text=False)
    rendered = cleanup_tables(rendered)
    normalized = decompose_html_structures(rendered)
    if hybrid.protected:
        normalized = restore_hybrid_pre_text(normalized, hybrid.protected)
    return normalized


__all__ = ["normalize_html_document"]
