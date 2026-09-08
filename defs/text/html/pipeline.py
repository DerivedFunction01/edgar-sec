"""String-first HTML document normalization pipeline."""

from __future__ import annotations

from collections.abc import Callable

from .cleaner import clean_html_for_parsing
from .decompose import decompose_html_structures


class NormalizedHtmlText(str):
    """String result of HTML normalization with retained table geometry metadata.

    Behaves identically to :class:`str` for comparisons and string methods
    while carrying a :class:`tuple` of :class:`TableGeometry` instances
    that describe the per-table row/cell geometry retained during
    normalization.
    """

    def __new__(cls, text: str, table_geometries: tuple = ()):
        instance = super().__new__(cls, text)
        instance._table_geometries = tuple(table_geometries)
        return instance

    @property
    def table_geometries(self) -> tuple:
        """Tuple of :class:`TableGeometry` instances, one per rendered table."""
        return self._table_geometries

    def __repr__(self) -> str:
        return (
            f"NormalizedHtmlText({super().__repr__()!r}, "
            f"table_geometries={self._table_geometries!r})"
        )


def normalize_html_document(
    html: str,
    *,
    cleanup_tables: Callable[[str], str] | None = None,
) -> NormalizedHtmlText:
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

    Returns a :class:`NormalizedHtmlText` that compares equal to the
    normalized text string while also exposing :attr:`table_geometries`
    with per-table row/cell geometry metadata.
    """
    if not html:
        return NormalizedHtmlText("", ())

    metadata_cleanup = cleanup_tables is None
    if metadata_cleanup:
        from defs.tables import cleanup_false_tables_with_metadata

    from defs.tables import convert_html_tables_to_ascii_with_metadata
    from defs.tables.hybrid import normalize_hybrid_pre_text, restore_hybrid_pre_text

    cleaned = clean_html_for_parsing(html)
    hybrid = normalize_hybrid_pre_text(cleaned)
    rendered, geometries = convert_html_tables_to_ascii_with_metadata(
        hybrid.text, convert_to_text=False
    )
    if metadata_cleanup:
        rendered, geometries = cleanup_false_tables_with_metadata(rendered, geometries)
    else:
        rendered = cleanup_tables(rendered)
    normalized = decompose_html_structures(rendered)
    if hybrid.protected:
        normalized = restore_hybrid_pre_text(normalized, hybrid.protected)
    return NormalizedHtmlText(normalized, geometries)


__all__ = ["NormalizedHtmlText", "normalize_html_document"]
