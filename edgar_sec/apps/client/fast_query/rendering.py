"""Filing rendering closure factory for fast-path filings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query.loaders import recover_inverted_primary
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.processing_profiles import (
    get_family_profile,
    get_lazy_index_trigger,
)
from edgar_sec.engine.document.screening import (
    screen_candidate_document,
    screen_specialized_xml_source,
)
from edgar_sec.engine.forms.render import UnsupportedRenderOperation, render_document
from edgar_sec.infra.sec_http.client import SecHttpClient


def make_filing_renderer(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
    operation: str | None = None,
    family_operations: dict[str, str] | None = None,
) -> Callable[..., str | bytes]:
    """Create a filing rendering closure with format dispatch and inversion recovery."""
    client_holder: list[SecHttpClient | None] = [None]
    default_op = operation

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _render(
        filing: FilingAggregate, operation: str | None = None, **kwargs: Any
    ) -> str | bytes:
        op = operation or (family_operations or {}).get(filing.form, default_op)
        source = filing.raw()
        if source is None:
            raise ValueError(
                f"Filing {filing.accession.raw} has no primary document bytes"
            )
        profile = get_family_profile(filing.form)
        resolved_op = op or (
            profile.preferred_operation.value
            if profile is not None and profile.preferred_operation is not None
            else AcquisitionOperation.RAW.value
        )
        if resolved_op == AcquisitionOperation.RAW.value:
            return source
        if resolved_op not in {
            AcquisitionOperation.RENDER_TO_TXT.value,
            AcquisitionOperation.RENDER_TO_XML.value,
        }:
            return source
        try:
            operation_kind = AcquisitionOperation(resolved_op)
        except ValueError:
            return source
        if profile is None or operation_kind not in profile.allowed_operations:
            return source

        trigger_enabled = get_lazy_index_trigger(filing.form) is not None
        candidate = screen_candidate_document(
            filing.form,
            filename=filing.primary_document_path,
            raw_content=source,
        )
        structure = (
            screen_specialized_xml_source(filing.form, source)
            if resolved_op == AcquisitionOperation.RENDER_TO_XML.value
            else None
        )
        mismatch = candidate.is_inversion or bool(structure and structure.is_inversion)

        recovered: bytes | None = None
        recovery_attempted = False
        if mismatch and trigger_enabled:
            recovery_attempted = True
            recovered = recover_inverted_primary(filing, doc_cache, _get_client)
            if recovered is not None:
                source = recovered
                candidate = screen_candidate_document(
                    filing.form,
                    filename=filing.primary_document_path,
                    raw_content=source,
                )
                structure = (
                    screen_specialized_xml_source(filing.form, source)
                    if resolved_op == AcquisitionOperation.RENDER_TO_XML.value
                    else None
                )
                mismatch = candidate.is_inversion or bool(
                    structure and structure.is_inversion
                )

        if resolved_op == AcquisitionOperation.RENDER_TO_XML.value and mismatch:
            return source

        try:
            rendered = _render_source(filing, source, resolved_op)
        except UnsupportedRenderOperation:
            return source

        if resolved_op == AcquisitionOperation.RENDER_TO_TXT.value and isinstance(
            rendered, str
        ):
            text_screen = screen_candidate_document(
                filing.form,
                filename=filing.primary_document_path,
                normalized_text=rendered,
            )
            if text_screen.is_inversion and trigger_enabled and not recovery_attempted:
                recovered = recover_inverted_primary(filing, doc_cache, _get_client)
                if recovered is not None:
                    return _render_source(filing, recovered, resolved_op)
        return rendered

    return _render


def _render_source(
    filing: FilingAggregate, source: bytes, operation: str
) -> str | bytes:
    return render_document(
        source,
        form=filing.form,
        filename=filing.primary_document_path,
        operation=operation,
    )
