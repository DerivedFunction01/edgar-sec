"""In-memory PDF byte builder for document tests."""

from __future__ import annotations


def make_pdf_bytes(pages: list[str | None]) -> bytes:
    """Build a small PDF in memory; a None page carries no text layer."""
    import pymupdf

    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text is not None:
            page.insert_text((72, 72), text, fontsize=11)
    try:
        return document.tobytes()
    finally:
        document.close()


__all__ = [
    "make_pdf_bytes",
]
