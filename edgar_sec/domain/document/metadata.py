"""Payload metadata records and detection functions for raw and rendered payloads."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.document.path_facts import (
    DocumentPathFacts,
    DocumentSuffixClass,
    mime_type_for_suffix,
)
from edgar_sec.domain.forms.common.processing import AcquisitionOperation


@dataclass(frozen=True, slots=True)
class PayloadMetadata:
    """Typed metadata describing a raw or rendered document payload."""

    suffix_class: DocumentSuffixClass
    suffix: str
    content_type: str
    is_binary: bool
    operation: str

    @property
    def format_name(self) -> str:
        """Ergonomic short format name (e.g. 'html', 'xml', 'txt', 'pdf')."""
        return self.suffix.lstrip(".").lower() or "bin"


def detect_raw_metadata(filename: str | None) -> PayloadMetadata:
    """Derive payload metadata for a raw primary or attachment document."""
    if not filename:
        return PayloadMetadata(
            suffix_class=DocumentSuffixClass.UNKNOWN,
            suffix="",
            content_type="application/octet-stream",
            is_binary=True,
            operation=AcquisitionOperation.RAW.value,
        )
    facts = DocumentPathFacts.from_archive_path(filename)
    mime = mime_type_for_suffix(filename)
    is_binary = facts.suffix_class in {
        DocumentSuffixClass.PDF,
        DocumentSuffixClass.IMAGE,
        DocumentSuffixClass.OPAQUE,
    }
    return PayloadMetadata(
        suffix_class=facts.suffix_class,
        suffix=facts.suffix,
        content_type=mime,
        is_binary=is_binary,
        operation=AcquisitionOperation.RAW.value,
    )


def detect_render_metadata(
    form: str | None,
    raw_meta: PayloadMetadata,
    operation: str | AcquisitionOperation | None = None,
) -> PayloadMetadata:
    """Derive payload metadata for the rendered output of a document."""
    op_str = (
        operation.value
        if isinstance(operation, AcquisitionOperation)
        else (str(operation).strip().lower() if operation else None)
    )

    if op_str in ("render_to_xml", "xml"):
        return PayloadMetadata(
            suffix_class=DocumentSuffixClass.XML,
            suffix=".xml",
            content_type="text/xml",
            is_binary=False,
            operation=AcquisitionOperation.RENDER_TO_XML.value,
        )

    if op_str in ("render_to_txt", "txt"):
        return PayloadMetadata(
            suffix_class=DocumentSuffixClass.TEXT,
            suffix=".txt",
            content_type="text/plain",
            is_binary=False,
            operation=AcquisitionOperation.RENDER_TO_TXT.value,
        )

    if op_str == "raw":
        return PayloadMetadata(
            suffix_class=raw_meta.suffix_class,
            suffix=raw_meta.suffix,
            content_type=raw_meta.content_type,
            is_binary=raw_meta.is_binary,
            operation=AcquisitionOperation.RAW.value,
        )

    if form:
        from edgar_sec.domain.forms.families.processing_profiles import (
            get_family_profile,
        )

        profile = get_family_profile(form)
        if profile and profile.preferred_operation:
            if profile.preferred_operation == AcquisitionOperation.RENDER_TO_XML:
                return PayloadMetadata(
                    suffix_class=DocumentSuffixClass.XML,
                    suffix=".xml",
                    content_type="text/xml",
                    is_binary=False,
                    operation=AcquisitionOperation.RENDER_TO_XML.value,
                )
            if profile.preferred_operation == AcquisitionOperation.RENDER_TO_TXT:
                return PayloadMetadata(
                    suffix_class=DocumentSuffixClass.TEXT,
                    suffix=".txt",
                    content_type="text/plain",
                    is_binary=False,
                    operation=AcquisitionOperation.RENDER_TO_TXT.value,
                )

    return PayloadMetadata(
        suffix_class=raw_meta.suffix_class,
        suffix=raw_meta.suffix,
        content_type=raw_meta.content_type,
        is_binary=raw_meta.is_binary,
        operation=AcquisitionOperation.RAW.value,
    )


__all__ = [
    "PayloadMetadata",
    "detect_raw_metadata",
    "detect_render_metadata",
]
