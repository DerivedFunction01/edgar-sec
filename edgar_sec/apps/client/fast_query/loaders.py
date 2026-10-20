"""Primary document, attachment, bundle, and index loaders for fast-path filings."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.document.path_facts import mime_type_for_suffix
from edgar_sec.domain.document_inventory.models import IndexPageInput, ParsedIndexPage
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.sec_urls import (
    accession_hyphenated,
    archives_url,
    full_submission_url_for,
    index_url_for,
)
from edgar_sec.engine.document.screening import (
    screen_candidate_document,
    screen_specialized_xml_source,
)
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.pipelines.document_acquisition.index_selection import select_index_entry


def resolve_primary_filename(filing: FilingAggregate) -> str:
    """Resolve filename for filing primary document."""
    if filing.primary_document_path:
        return Path(filing.primary_document_path).name
    if filing.primary_document_url:
        leaf = filing.primary_document_url.rsplit("/", 1)[-1]
        if leaf:
            return leaf
    return f"{accession_hyphenated(filing.accession.value)}.txt"


def resolve_primary_url(filing: FilingAggregate) -> str:
    """Resolve archive or full submission URL for primary document."""
    if filing.primary_document_url:
        return filing.primary_document_url
    fname = resolve_primary_filename(filing)
    if fname.endswith(".txt"):
        return full_submission_url_for(
            str(filing.primary_cik.value), filing.accession.value
        )
    return archives_url(filing.primary_cik.value, filing.accession.value, fname)


def recover_inverted_primary(
    filing: FilingAggregate,
    cache: DocumentCache,
    get_client: Callable[[], SecHttpClient],
) -> bytes | None:
    """Recover true primary document via lazy index parsing on inversion."""
    idx_name = f"{filing.accession.raw}-index.html"
    idx_bytes = cache.get(filing.accession.raw, idx_name)
    url = index_url_for(filing.accession, filing.primary_cik)
    if idx_bytes is None:
        client = get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is not None:
            idx_bytes = fetch_fn(url)
            if idx_bytes:
                cache.put(
                    accession=filing.accession.raw,
                    cik=str(filing.primary_cik.value),
                    form=filing.form,
                    filename=idx_name,
                    content=idx_bytes,
                    content_type="text/html",
                )
    if not idx_bytes:
        return None

    parsed = parse_html_index(IndexPageInput(filing.accession, url, idx_bytes))
    if not isinstance(parsed, ParsedIndexPage):
        return None

    selection = select_index_entry(
        parsed,
        accession=filing.accession,
        expected_form=filing.form,
        optional=False,
    )
    if selection.result != "selected" or not selection.entry:
        return None

    recovered_name = selection.entry.filename or ""
    if not recovered_name:
        return None

    cached_rec = cache.get(filing.accession.raw, recovered_name)
    if cached_rec is not None:
        if not _is_expected_primary(filing.form, recovered_name, cached_rec):
            return None
        object.__setattr__(filing, "primary_document_path", recovered_name)
        if selection.entry.archive_url:
            object.__setattr__(
                filing, "primary_document_url", selection.entry.archive_url
            )
        return cached_rec

    fetch_url = selection.entry.archive_url or archives_url(
        filing.primary_cik.value, filing.accession.raw, recovered_name
    )
    client = get_client()
    fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
    if fetch_fn is None:
        return None
    rec_bytes = fetch_fn(fetch_url)
    if rec_bytes is not None:
        if not _is_expected_primary(filing.form, recovered_name, rec_bytes):
            return None
        cache.put(
            accession=filing.accession.raw,
            cik=str(filing.primary_cik.value),
            form=filing.form,
            filename=recovered_name,
            content=rec_bytes,
            content_type=mime_type_for_suffix(recovered_name),
        )
        object.__setattr__(filing, "primary_document_path", recovered_name)
        object.__setattr__(filing, "primary_document_url", fetch_url)
        return rec_bytes
    return None


def _is_expected_primary(form: str, filename: str, content: bytes) -> bool:
    candidate = screen_candidate_document(form, filename=filename, raw_content=content)
    if candidate.is_inversion:
        return False
    structure = screen_specialized_xml_source(form, content)
    return not structure.is_inversion


def make_document_fetcher(
    cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], bytes | None]:
    """Create a lazy document fetcher closure bound to cache and HTTP client."""
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _fetch(filing: FilingAggregate) -> bytes | None:
        filename = resolve_primary_filename(filing)
        acc_str = filing.accession.value

        screen = screen_candidate_document(filing.form, filename=filename)
        if screen.is_inversion:
            recovered = recover_inverted_primary(filing, cache, _get_client)
            if recovered is not None:
                return recovered

        cached = cache.get(acc_str, filename)
        if cached is not None:
            screen = screen_candidate_document(
                filing.form, filename=filename, raw_content=cached
            )
            if screen.is_inversion:
                recovered = recover_inverted_primary(filing, cache, _get_client)
                if recovered is not None:
                    return recovered
            return cached

        url = resolve_primary_url(filing)
        if not url:
            return None

        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        response_bytes = fetch_fn(url)
        if response_bytes is not None:
            c_type = mime_type_for_suffix(filename)
            cache.put(
                accession=acc_str,
                cik=filing.primary_cik.value,
                form=filing.form,
                filename=filename,
                content=response_bytes,
                content_type=c_type,
            )
            screen = screen_candidate_document(
                filing.form, filename=filename, raw_content=response_bytes
            )
            if screen.is_inversion:
                recovered = recover_inverted_primary(filing, cache, _get_client)
                if recovered is not None:
                    return recovered
        return response_bytes

    return _fetch


def make_attachment_loader(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], tuple[FilingAttachment, ...]]:
    """Create a lazy attachment loader closure querying the -index.html page."""
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _load(filing: FilingAggregate) -> tuple[FilingAttachment, ...]:
        fname = f"{filing.accession.raw}-index.html"
        html_bytes = doc_cache.get(filing.accession.raw, fname)
        url = index_url_for(filing.accession, filing.primary_cik)
        if html_bytes is None:
            client = _get_client()
            fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
            if fetch_fn is None:
                return ()
            try:
                html_bytes = fetch_fn(url)
            except Exception:
                return ()
            if html_bytes:
                doc_cache.put(
                    accession=filing.accession.raw,
                    cik=str(filing.primary_cik.value),
                    form=filing.form,
                    filename=fname,
                    content=html_bytes,
                    content_type="text/html",
                )
        if not html_bytes:
            return ()
        outcome = parse_html_index(
            IndexPageInput(
                accession=filing.accession,
                source_url=url,
                response_bytes=html_bytes,
            )
        )
        if not isinstance(outcome, ParsedIndexPage):
            return ()

        def _make_att_fetcher(
            target_url: str, fname: str
        ) -> Callable[[FilingAttachment], bytes | None]:
            def _fetch_att(_att: FilingAttachment) -> bytes | None:
                cached = doc_cache.get(filing.accession.raw, fname)
                if cached is not None:
                    return cached
                if not target_url:
                    return None
                cli = _get_client()
                fn = getattr(cli, "get_bytes", getattr(cli, "get", None))
                if fn is None:
                    return None
                data = fn(target_url)
                if data:
                    doc_cache.put(
                        accession=filing.accession.raw,
                        cik=str(filing.primary_cik.value),
                        form=filing.form,
                        filename=fname,
                        content=data,
                        content_type=mime_type_for_suffix(fname),
                    )
                    return data
                return None

            return _fetch_att

        def _make_att_renderer(
            entry_type: str, fname: str
        ) -> Callable[[FilingAttachment], str | bytes | None]:
            def _render_att(att: FilingAttachment) -> str | bytes | None:
                raw_b = att.raw()
                if raw_b is None:
                    return None
                if att.is_graphic:
                    return raw_b
                from edgar_sec.engine.forms.render import render_document

                return render_document(
                    raw_b,
                    form=entry_type or att.document_type,
                    filename=fname or att.filename,
                    operation=AcquisitionOperation.RENDER_TO_TXT,
                )

            return _render_att

        attachments: list[FilingAttachment] = []
        for entry in outcome.entries:
            fname = entry.filename or ""
            a_url = entry.archive_url or ""
            dtype = entry.document_type or ""
            attachments.append(
                FilingAttachment(
                    attachment_id=str(entry.sequence or fname or ""),
                    document_type=dtype,
                    filename=fname,
                    url=a_url,
                    size=entry.byte_size,
                    description=entry.description,
                    fetcher=_make_att_fetcher(a_url, fname) if a_url else None,
                    renderer=_make_att_renderer(dtype, fname),
                )
            )
        return tuple(attachments)

    return _load


def make_document_opener(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate, str], bytes | None]:
    """Create a document opener closure bound to cache and HTTP client."""
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _open(filing: FilingAggregate, filename: str) -> bytes | None:
        cached = doc_cache.get(filing.accession.raw, filename)
        if cached is not None:
            return cached
        url = archives_url(filing.primary_cik.value, filing.accession.raw, filename)
        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        data = fetch_fn(url)
        if data:
            doc_cache.put(
                accession=filing.accession.raw,
                cik=str(filing.primary_cik.value),
                form=filing.form,
                filename=filename,
                content=data,
                content_type=mime_type_for_suffix(filename),
            )
            return data
        return None

    return _open


def make_bundle_fetcher(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], bytes | None]:
    """Create a lazy submission bundle (.txt) fetcher closure."""
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _fetch(filing: FilingAggregate) -> bytes | None:
        fname = f"{filing.accession.raw}.txt"
        cached = doc_cache.get(filing.accession.raw, fname)
        if cached is not None:
            return cached
        url = full_submission_url_for(
            str(filing.primary_cik.value), filing.accession.raw
        )
        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        data = fetch_fn(url)
        if data:
            doc_cache.put(
                accession=filing.accession.raw,
                cik=str(filing.primary_cik.value),
                form=filing.form,
                filename=fname,
                content=data,
                content_type="text/plain",
            )
            return data
        return None

    return _fetch


def make_index_fetcher(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], str | None]:
    """Create a lazy index HTML fetcher closure."""
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _fetch(filing: FilingAggregate) -> str | None:
        fname = f"{filing.accession.raw}-index.html"
        cached = doc_cache.get(filing.accession.raw, fname)
        if cached is not None:
            return cached.decode("utf-8", errors="replace")
        url = index_url_for(filing.accession, filing.primary_cik)
        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        data = fetch_fn(url)
        if data:
            doc_cache.put(
                accession=filing.accession.raw,
                cik=str(filing.primary_cik.value),
                form=filing.form,
                filename=fname,
                content=data,
                content_type="text/html",
            )
            return data.decode("utf-8", errors="replace")
        return None

    return _fetch
