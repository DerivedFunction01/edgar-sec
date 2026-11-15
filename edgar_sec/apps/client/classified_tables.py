"""Classified tables, fast version: one-off filings on demand (D2).

The fast path calls the one engine context production in the call;
its derived products are cached in the facade content cache.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.apps.client.content_cache import ContentCache, estimate_retained_bytes
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.exhibit_resolution import (
    ExhibitCandidateInput,
    resolve_exhibits,
)
from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.engine.tables.extraction.classify import classify_filing
from edgar_sec.engine.tables.extraction.context_production import (
    DocumentInput,
    ProductionResult,
    produce_contexts,
)
from edgar_sec.engine.tables.extraction.profiles import PROV_STEP6_VERDICT
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

#: Cache stamp: registry provenance plus the production version.
CLASSIFIED_STAMP = f"classified-v1:{PROV_STEP6_VERDICT}"
_KIND = f"classified_tables:{CLASSIFIED_STAMP}"


@dataclass(frozen=True, slots=True)
class ClassifiedTable:
    """One classified geometry: family, tier, score, source document."""

    table_index: int
    source_document: str | None
    family: str
    tier: str
    score: float


def _produce(filing: FilingAggregate, stratum: str | None) -> ProductionResult:
    """Normalize the filing's documents and produce their contexts."""
    raw = filing.raw()
    if raw is None:
        return ProductionResult(documents=())
    primary = normalize_document(
        raw,
        form=filing.form,
        document_path=filing.primary_document_path or None,
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    documents = [DocumentInput("primary", primary)]
    if stratum is not None:
        candidates = []
        exhibit_results = {}
        for attachment in filing.exhibits():
            payload = attachment.raw()
            if payload is None:
                continue
            result = normalize_document(
                payload,
                form=filing.form,
                document_path=attachment.filename,
                page_policy=PageArtifactPolicy.ANNOTATE,
            )
            exhibit_results[attachment.filename] = result
            candidates.append(
                ExhibitCandidateInput(
                    document_type=attachment.document_type,
                    document_name=attachment.filename,
                    body_text=result.text,
                )
            )
        resolved = resolve_exhibits(
            tuple(candidates),
            stratum=stratum,
            filing_form=filing.form,
            primary_text=primary.text,
        )
        documents.extend(
            DocumentInput(entry.document_name, exhibit_results[entry.document_name])
            for entry in resolved
            if entry.body_confirmed
        )
    return produce_contexts(tuple(documents))


def classified_tables_fast(
    cache: ContentCache,
    filing: FilingAggregate,
    *,
    stratum: str | None = None,
) -> tuple[ClassifiedTable, ...]:
    """Classify one filing's tables on demand, caching the products.

    The produced contexts are the cached derived product; the cascade
    re-runs over them per call, never serving a stale classification.
    """

    def build() -> tuple[ProductionResult, int]:
        production = _produce(filing, stratum)
        return production, estimate_retained_bytes(production)

    production: ProductionResult = cache.get_or_build(
        (_KIND, filing.accession.value), build
    )
    contexts = production.contexts
    if not contexts:
        return ()
    tables = [structure_table(context) for context in contexts]
    classifications, _scores = classify_filing(tables)
    return tuple(
        ClassifiedTable(
            table_index=context.table_index,
            source_document=context.source_document,
            family=result.family,
            tier=result.tier,
            score=result.score,
        )
        for context, result in zip(contexts, classifications, strict=True)
    )
