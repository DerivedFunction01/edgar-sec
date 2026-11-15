"""Catalog-free primary-document retrieval for venues without a catalog.

Adapted from the taxonomy lane's recorded substitution for the same
wall: the facade's fetch-by-accession requires a published filing
catalog in the artifacts root, which no live session carries. Builds
each filing's aggregate straight from its Archives index — one index
request names every document; the primary document's bytes come back
through the repo's rate-limited SEC client. URLs are built only by
``edgar_sec.domain.sec_urls``.
"""

from __future__ import annotations

import html

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    ParsedIndexPage,
)
from edgar_sec.domain.forms.exhibits.vocabulary import is_ex13_type
from edgar_sec.engine.forms.exhibit_resolution import linked_exhibit_families
from edgar_sec.pipelines.document_planning.profiles import (
    get_or_create_exhibit_profile,
    targets_for_form,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import archives_url, index_json_url_for, index_url_for
from edgar_sec.engine.document.unpacking.unpacker import unpack_sgml_submission
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.foundation.runtime.settings.sec import (
    DEFAULT_RATE_LIMIT_RPS,
    SecSettings,
)
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter


def make_client(workers: int) -> SecHttpClient:
    """Per-worker client; per-worker rate shares sum to the global cap."""
    user_agent = get_env("SEC_USER_AGENT") or SecSettings().header_user_agent
    limiter = RateLimiter(min_interval_s=workers / DEFAULT_RATE_LIMIT_RPS)
    return SecHttpClient(user_agent=user_agent, rate_limiter=limiter)


_INDEX_SUFFIXES = ("-index.html", "-index-headers.html", "-index-headers.txt")


def _index_page_primary(
    client: SecHttpClient, cik: Cik, accession: AccessionNumber, form: str
) -> str:
    """Primary filename from the filing index page, or ''.

    The repo's index-page parser is the planning vehicle for sequence
    and type; among entries typed as the filing's form, the lowest
    sequence is the primary.
    """
    url = index_url_for(accession, cik)
    try:
        raw = client.get_bytes(url)
    except Exception:  # noqa: BLE001 - an unserved page is a route miss
        return ""
    outcome = parse_html_index(
        IndexPageInput(accession=accession, source_url=url, response_bytes=raw)
    )
    if not isinstance(outcome, ParsedIndexPage):
        return ""
    best: tuple[int, str] | None = None
    for entry in outcome.entries:
        if (
            entry.document_type
            and entry.document_type.strip().upper() == form.strip().upper()
            and entry.filename
        ):
            sequence = entry.sequence if entry.sequence is not None else 9999
            if best is None or sequence < best[0]:
                best = (sequence, entry.filename)
    return best[1] if best else ""


def _largest_document(items: list, accession_raw: str) -> str:
    """Largest content document, excluding index artifacts and the
    accession-named complete-submission text (it bundles every exhibit)."""
    pool = [
        item
        for item in items
        if not str(item["name"]).lower().endswith(_INDEX_SUFFIXES)
        and str(item["name"]) != f"{accession_raw}.txt"
        and str(item["name"]).lower().endswith((".htm", ".html", ".txt"))
    ]
    if not pool:
        return ""
    return str(max(pool, key=lambda item: int(item.get("size") or 0))["name"])


def _headers_primary(
    client: SecHttpClient, cik: Cik, accession: AccessionNumber, form: str
) -> str:
    """Primary filename from the filing's SGML index headers, or ''.

    The Archives directory listing carries no document types (its type
    field is a file icon); the SGML headers are the authoritative
    per-document type record. Among documents typed as the filing's
    form, the lowest sequence number is the primary.
    """
    for suffix in ("-index-headers.txt", "-index-headers.html"):
        try:
            raw = client.get_bytes(
                archives_url(cik.value, accession.raw, f"{accession.raw}{suffix}")
            )
        except Exception:  # noqa: BLE001 - a missing variant is expected
            continue
        text = html.unescape(raw.decode("utf-8", errors="ignore"))
        best: tuple[int, str] | None = None
        for doc in unpack_sgml_submission(text):
            if doc.doc_type == form.strip().upper() and doc.filename:
                sequence = (
                    doc.sequence
                    if doc.sequence is not None and doc.sequence >= 0
                    else 9999
                )
                if best is None or sequence < best[0]:
                    best = (sequence, doc.filename)
        if best is not None:
            return best[1]
    return ""


def _header_types(
    client: SecHttpClient, cik: Cik, accession: AccessionNumber
) -> dict[str, str]:
    """Per-document index types from the SGML index headers.

    The Archives directory listing carries no document types (its
    type field is a file icon); the headers are the authoritative
    per-document type record the census's index TYPE route read.
    """
    types: dict[str, str] = {}
    for suffix in ("-index-headers.txt", "-index-headers.html"):
        try:
            raw = client.get_bytes(
                archives_url(cik.value, accession.raw, f"{accession.raw}{suffix}")
            )
        except Exception:  # noqa: BLE001 - a missing variant is expected
            continue
        text = html.unescape(raw.decode("utf-8", errors="ignore"))
        for doc in unpack_sgml_submission(text):
            if doc.filename and doc.doc_type:
                types[doc.filename] = doc.doc_type
        if types:
            break
    return types


def _index_page_types(
    client: SecHttpClient, cik: Cik, accession: AccessionNumber
) -> dict[str, str]:
    """Per-document index types from the filing index page.

    Older filings' index headers carry no document blocks; the
    index page's TYPE column is the census route for those eras.
    """
    url = index_url_for(accession, cik)
    try:
        raw = client.get_bytes(url)
    except Exception:  # noqa: BLE001 - an unserved page is a route miss
        return {}
    outcome = parse_html_index(
        IndexPageInput(accession=accession, source_url=url, response_bytes=raw)
    )
    if not isinstance(outcome, ParsedIndexPage):
        return {}
    return {
        entry.filename: entry.document_type
        for entry in outcome.entries
        if entry.filename and entry.document_type
    }


def build_aggregate(
    client: SecHttpClient, spec: dict[str, object]
) -> tuple[FilingAggregate, str]:
    """Assemble one filing's aggregate from its Archives index.

    Returns the aggregate and the primary document's source: ``spec``
    when the caller named it, else the index derivation rule used.
    """
    cik = Cik.from_raw(str(spec["cik"]))
    accession = AccessionNumber(str(spec["accession"]))
    index = client.get_json(index_json_url_for(accession, cik))
    items = index["directory"]["item"]
    header_types = _header_types(client, cik, accession)
    for name, doc_type in _index_page_types(client, cik, accession).items():
        header_types.setdefault(name, doc_type)

    def _fetcher(url: str):  # noqa: ANN202
        return lambda att: client.get_bytes(url)

    attachments: list[FilingAttachment] = []
    has_instance = False
    for item in items:
        name = str(item["name"])
        doc_type = header_types.get(name) or str(item.get("type") or "")
        if doc_type.upper() == "EX-101.INS" or name.lower().endswith("_htm.xml"):
            has_instance = True
        size_raw = str(item.get("size") or "")
        attachments.append(
            FilingAttachment(
                attachment_id=name,
                document_type=doc_type,
                filename=name,
                url=archives_url(cik.value, accession.raw, name),
                size=int(size_raw) if size_raw.isdigit() else None,
                fetcher=_fetcher(archives_url(cik.value, accession.raw, name)),
            )
        )
    primary_name = str(spec.get("primary_document") or "")
    source = "spec"
    if not primary_name:
        primary_name = _headers_primary(client, cik, accession, str(spec["form"]))
        source = "sgml-headers" if primary_name else ""
    if not primary_name:
        primary_name = _index_page_primary(client, cik, accession, str(spec["form"]))
        source = "index-page" if primary_name else "index-largest"
        if not primary_name:
            primary_name = _largest_document(items, accession.raw)
    if spec.get("is_inline_xbrl") and not has_instance and primary_name:
        attachments.append(
            FilingAttachment(
                attachment_id=f"{primary_name}#inline-instance",
                document_type="EX-101.INS",
                filename=primary_name,
                url=archives_url(cik.value, accession.raw, primary_name),
                fetcher=_fetcher(archives_url(cik.value, accession.raw, primary_name)),
            )
        )
    aggregate = FilingAggregate(
        accession=accession,
        primary_cik=cik,
        ciks=(cik,),
        form=str(spec["form"]),
        filing_date=str(spec["filing_date"]),
        primary_document_path=archives_url(cik.value, accession.raw, primary_name),
        attachments=tuple(attachments),
        fetcher=lambda filing: client.get_bytes(
            archives_url(cik.value, accession.raw, primary_name)
        ),
    )
    return aggregate, source


def primary_bytes(filing: FilingAggregate) -> bytes | None:
    """Primary document bytes from an aggregate (the incumbent's rule)."""
    if filing.fetcher is not None:
        data = filing.fetcher(filing)
        if data:
            return data
    target = (filing.primary_document_path or "").rsplit("/", 1)[-1]
    for att in filing.get_attachments():
        if (att.filename or "") == target:
            return att.raw()
    return None


def declared_exhibit_targets(
    stratum: str, profiles_root: str | None = None
) -> tuple[dict, ...]:
    """Declared exhibit targets for one registry stratum.

    The registry link lives here, on the consumer side: each linked
    base type is translated through planning's generic declaration,
    which emits the role/type/optional triple and learns nothing
    about the classifier. Planning never imports the registry.
    """
    targets: list[dict] = []
    for base_type in linked_exhibit_families(stratum):
        profile = get_or_create_exhibit_profile(
            base_type, profiles_root=profiles_root
        )
        for target in targets_for_form(profile, "*"):
            if target.role == "exhibit":
                targets.append(
                    {
                        "role": target.role,
                        "type": target.type,
                        "optional": target.optional,
                    }
                )
    return tuple(targets)


def _is_metadata_candidate(document_type: str | None, declared_type: str) -> bool:
    """Metadata candidacy of one index type against a declared type."""
    if declared_type == "EX-13":
        return is_ex13_type(document_type)
    if not document_type:
        return False
    value = document_type.strip().upper()
    return value == declared_type or value.startswith(f"{declared_type}.")


def exhibit_candidates(
    filing: FilingAggregate, declared_types: tuple[str, ...]
) -> tuple[FilingAttachment, ...]:
    """Attachments flagged by index metadata alone; no body is read.

    The primary document is never its own exhibit candidate, and a
    document matching several declared types is returned once.
    """
    primary_name = (filing.primary_document_path or "").rsplit("/", 1)[-1]
    candidates: list[FilingAttachment] = []
    for attachment in filing.get_attachments():
        if (attachment.filename or "") == primary_name:
            continue
        if any(
            _is_metadata_candidate(attachment.document_type, declared)
            for declared in declared_types
        ):
            candidates.append(attachment)
    return tuple(candidates)


def collect_exhibits(
    filing: FilingAggregate, declared_types: tuple[str, ...]
) -> tuple[dict, ...]:
    """Fetch bytes for metadata-flagged candidates only.

    Returns the inventory dicts ``extract_filing`` consumes; body
    confirmation is the resolver's, downstream of this fetch.
    """
    exhibits: list[dict] = []
    for attachment in exhibit_candidates(filing, declared_types):
        raw = attachment.raw()
        if raw is None:
            continue
        exhibits.append(
            {
                "document_type": attachment.document_type,
                "document_name": attachment.filename or attachment.attachment_id,
                "raw": raw,
            }
        )
    return tuple(exhibits)
