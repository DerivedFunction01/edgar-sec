"""Classified tables, fast version: one-off filings on demand (D2).

The fast path calls the one engine context production in the call;
its derived products are cached in the facade content cache.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.apps.client.caching.content_cache import (
    ContentCache,
    estimate_retained_bytes,
)
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.cover.profiles import get_profile
from edgar_sec.engine.forms.exhibit_resolution import (
    ExhibitCandidateInput,
    resolve_exhibits,
)
from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.tables.extraction.cascade.scoring.classify import classify_filing
from edgar_sec.engine.tables.extraction.assembly.context_production import (
    DocumentInput,
    ProductionResult,
    produce_contexts,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import registry_state
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

#: Origin stamped on every row this path serves (D2 duality).
ORIGIN_FAST = "fast"
#: Stamp format version: the stamp shape both facade versions share.
STAMP_VERSION = "classified-v1"


def build_stamp(*, normalize_version: str, renderer_version: str) -> str:
    """The shared stamp string: registry state + normalize/renderer versions."""
    registry = registry_state().removeprefix("sha256:")
    return (
        f"{STAMP_VERSION};registry={registry}"
        f";normalize={normalize_version};renderer={renderer_version}"
    )


def cache_kind(*, normalize_version: str, stratum: str | None) -> str:
    """The stamped cache kind under which one stratum's products sit."""
    return (
        f"classified_tables:{ORIGIN_FAST}:{registry_state()}"
        f":{normalize_version}:{stratum or 'primary'}"
    )


@dataclass(frozen=True, slots=True)
class ClassifiedTable:
    """One classified geometry: family, tier, score, source, stamp."""

    table_index: int
    source_document: str | None
    family: str
    tier: str
    score: float
    origin: str
    stamp: str


@dataclass(frozen=True, slots=True)
class _CachedProduction:
    """One filing's cached derived products and the stamp they carry."""

    production: ProductionResult
    stamp: str


def _renderer_version(results: list[NormalizationResult], fallback: str) -> str:
    """The renderer version the produced sequences record, else fallback."""
    for result in results:
        for sequence in (result.sections, result.notes):
            if sequence is not None and sequence.renderer_version:
                return sequence.renderer_version
    return fallback


def _produce(
    filing: FilingAggregate, stratum: str | None, normalize_version: str
) -> _CachedProduction:
    """Normalize the filing's documents and produce their contexts."""
    raw = filing.raw()
    if raw is None:
        stamp = build_stamp(
            normalize_version=normalize_version, renderer_version=normalize_version
        )
        return _CachedProduction(ProductionResult(documents=()), stamp)
    primary = normalize_document(
        raw,
        form=filing.form,
        document_path=filing.primary_document_path or None,
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    results = [primary]
    documents = [DocumentInput("primary", primary)]
    if stratum is not None:
        candidates = []
        exhibit_results = {}
        for attachment in filing.exhibits:
            payload = attachment.raw()
            if payload is None:
                continue
            result = normalize_document(
                payload,
                form=filing.form,
                document_path=attachment.filename,
                page_policy=PageArtifactPolicy.ANNOTATE,
            )
            results.append(result)
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
    stamp = build_stamp(
        normalize_version=normalize_version,
        renderer_version=_renderer_version(results, normalize_version),
    )
    return _CachedProduction(produce_contexts(tuple(documents)), stamp)


def classified_tables_fast(
    cache: ContentCache,
    filing: FilingAggregate,
    *,
    stratum: str | None = None,
) -> tuple[ClassifiedTable, ...]:
    """Classify one filing's tables on demand, caching the products.

    Produced contexts (HTML geometries included) are cached under the
    stamped kind for the filing's stratum; the cascade re-runs per call.
    """
    normalize_version = get_profile(filing.form).version
    kind = cache_kind(normalize_version=normalize_version, stratum=stratum)

    def build() -> tuple[_CachedProduction, int]:
        cached = _produce(filing, stratum, normalize_version)
        return cached, estimate_retained_bytes(cached)

    cached: _CachedProduction = cache.get_or_build(
        (kind, filing.accession.value), build
    )
    contexts = cached.production.contexts
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
            origin=ORIGIN_FAST,
            stamp=cached.stamp,
        )
        for context, result in zip(contexts, classifications, strict=True)
    )
