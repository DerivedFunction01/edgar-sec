"""Amendment-lineage discovery for the production facade.

Local submissions snapshot only, never a live fetch: a filing the
snapshot does not cover keeps the single-filing path unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.engine.xbrl.solve.scoping import FilingRef, base_form, build_lineages

if TYPE_CHECKING:
    from edgar_sec.apps.client.cache import DocumentCache
    from edgar_sec.infra.sec_http.client import SecHttpClient


def filing_ref(filing: FilingAggregate) -> FilingRef | None:
    """The scoping ref for a filing, or None without a report period."""
    if not filing.report_date:
        return None
    return FilingRef(
        cik=filing.primary_cik.to_10digit(),
        accession=filing.accession.value,
        form=filing.form,
        report_period=filing.report_date,
        filed_date=filing.filing_date,
    )


def lineage_group(
    filing: FilingAggregate,
    candidates: Iterable[FilingAggregate],
) -> tuple[FilingAggregate, ...]:
    """The amendment group around a filing, ordered as its lineage reads.

    Same filer, base form, and report period only; empty unless a real
    lineage (original plus amendment) covers the filing itself.
    """
    target = filing_ref(filing)
    if target is None:
        return ()
    members: dict[str, FilingAggregate] = {target.accession: filing}
    for candidate in candidates:
        ref = filing_ref(candidate)
        if ref is None or ref.cik != target.cik:
            continue
        if (
            base_form(ref.form) != base_form(target.form)
            or ref.report_period != target.report_period
        ):
            continue
        members.setdefault(ref.accession, candidate)
    refs = tuple(filing_ref(member) for member in members.values())
    for lineage in build_lineages(tuple(ref for ref in refs if ref is not None)):
        if target.accession in lineage.accessions and len(lineage.accessions) > 1:
            return tuple(members[accession] for accession in lineage.accessions)
    return ()


def discover_lineage_group(
    filing: FilingAggregate,
    *,
    artifacts_root: Path | str,
    doc_cache: "DocumentCache",
    http_client_factory: Callable[[], "SecHttpClient"],
) -> tuple[FilingAggregate, ...]:
    """The filing's amendment group from the local submissions snapshot."""
    target = filing_ref(filing)
    if target is None:
        return ()
    from edgar_sec.apps.client.fast_query.loaders import make_attachment_loader
    from edgar_sec.apps.client.fast_query.submissions_local import (
        materialize_from_snapshot,
    )

    base = base_form(target.form)
    forms = (base, f"{base}/A")
    covered = materialize_from_snapshot(
        [filing.primary_cik],
        forms,
        None,
        None,
        {"attachment_loader": make_attachment_loader(doc_cache, http_client_factory)},
        doc_cache,
        artifacts_root=artifacts_root,
    )
    candidates = covered.get(filing.primary_cik.to_10digit()) or ()
    return lineage_group(filing, candidates)
