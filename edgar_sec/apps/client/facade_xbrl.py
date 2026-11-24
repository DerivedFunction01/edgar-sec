"""XBRL facade construction surface of the Edgar facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edgar_sec.apps.client.xbrl import Xbrl
    from edgar_sec.domain.document.aggregate import FilingAggregate


class XbrlMixin:
    """XBRL construction methods composed into the Edgar facade."""

    def xbrl(self, filing: FilingAggregate) -> Xbrl:
        """Parse linkbases and return unified interactive Xbrl facade."""
        key = (filing.primary_cik.to_10digit(), filing.accession.value)
        return self.facade_cache.get_or_build(key, lambda: self._build_xbrl(filing))

    def _build_xbrl(self, filing: FilingAggregate) -> Xbrl:
        """Build one filing's facade, pooling its amendment lineage if any.

        No local submissions row for the group means the single-filing path.
        """
        from edgar_sec.apps.client.financials.lineages import (
            discover_lineage_group,
            filing_ref,
        )
        from edgar_sec.apps.client.xbrl import Xbrl
        from edgar_sec.engine.xbrl.parsing.filing_parser import parse_filing_xbrl
        from edgar_sec.engine.xbrl.solve.core.scoping import build_lineages
        from edgar_sec.foundation.runtime.paths import resolve_paths

        if filing_ref(filing) is None:
            return Xbrl(parse_filing_xbrl(filing))
        group = discover_lineage_group(
            filing,
            artifacts_root=(
                self.artifacts_root
                if self.artifacts_root is not None
                else resolve_paths().artifacts_root
            ),
            doc_cache=self.cache,
            http_client_factory=lambda: self.sec_client,
        )
        if not group:
            return Xbrl(parse_filing_xbrl(filing))
        refs = tuple(ref for member in group if (ref := filing_ref(member)) is not None)
        parsed = {member.accession.value: parse_filing_xbrl(member) for member in group}
        fact_pool = tuple(
            fact for member in group for fact in parsed[member.accession.value].facts
        )
        return Xbrl(
            parsed[filing.accession.value],
            lineages=build_lineages(refs),
            fact_pool=fact_pool,
        )
