"""Filing rendering closure factory for fast-path filings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query.loaders import recover_inverted_primary
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.engine.document.screening import screen_candidate_document
from edgar_sec.engine.forms.render import render_filing
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
        rendered = render_filing(filing, operation=op)
        if isinstance(rendered, str):
            screen = screen_candidate_document(
                filing.form,
                filename=filing.primary_document_path,
                normalized_text=rendered,
            )
            if screen.is_inversion:
                recovered = recover_inverted_primary(filing, doc_cache, _get_client)
                if recovered is not None:
                    return render_filing(filing, operation=op)
        return rendered

    return _render
