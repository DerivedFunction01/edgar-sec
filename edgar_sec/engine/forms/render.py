"""Multi-modal document and filing rendering dispatcher.

Routes payloads to text normalization, XML rendering, or raw byte pass-through
based on declared form-family processing profiles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile

if TYPE_CHECKING:
    from edgar_sec.domain.document.aggregate import FilingAggregate


class UnsupportedRenderOperation(ValueError):
    """Raised when an unsupported render operation is requested for a form."""


def render_document(
    raw_bytes: bytes,
    *,
    form: str | None = None,
    filename: str | None = None,
    operation: AcquisitionOperation | None = None,
) -> str | bytes:
    """Render raw document bytes according to form family profile or target operation."""
    profile = get_family_profile(form) if form else None
    target_op = operation or (
        profile.preferred_operation if profile else AcquisitionOperation.RAW
    )

    if target_op == AcquisitionOperation.RENDER_TO_TXT:
        if profile and not profile.has_operation(AcquisitionOperation.RENDER_TO_TXT):
            raise UnsupportedRenderOperation(
                f"Form {form!r} does not support text rendering; use .xml() or .raw()"
            )
        from edgar_sec.engine.forms.normalize import normalize_document

        return normalize_document(
            raw_bytes,
            form=form,
            document_path=filename,
        ).text

    if target_op == AcquisitionOperation.RENDER_TO_XML:
        if profile and not profile.has_operation(AcquisitionOperation.RENDER_TO_XML):
            raise UnsupportedRenderOperation(
                f"Form {form!r} does not support XML rendering; use .text() or .raw()"
            )
        from edgar_sec.engine.forms.ownership.render_to_xml import render_form4_to_xml

        xml_bytes = render_form4_to_xml(raw_bytes)
        return xml_bytes.decode("utf-8", errors="replace")

    return raw_bytes


def render_filing(
    filing: FilingAggregate,
    *,
    operation: AcquisitionOperation | None = None,
) -> str | bytes:
    """Render the primary document of a filing aggregate."""
    raw_data = filing.raw()
    if raw_data is None:
        raise ValueError(f"Filing {filing.accession.raw} has no primary document bytes")
    return render_document(
        raw_data,
        form=filing.form,
        filename=filing.primary_document_path,
        operation=operation,
    )


__all__ = [
    "UnsupportedRenderOperation",
    "render_document",
    "render_filing",
]
