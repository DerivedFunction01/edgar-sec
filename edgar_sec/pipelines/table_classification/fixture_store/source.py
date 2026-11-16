"""Fixture-backed filing source for review runs.

Mirrors the worker's FilingSource seam — documents_for(accession,
targets) — but payloads carry stored computed products, never raw
bytes: a fixture source never feeds a re-normalization.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.engine.forms.normalize import NormalizationResult

from .models import ProductStamps
from .reader import iter_case_results


@dataclass(frozen=True, slots=True)
class FixtureDocumentPayload:
    """One fixture document: its identity and rebuilt products."""

    document_name: str
    target_role: str
    target_type: str
    result: NormalizationResult
    stamps: ProductStamps


@dataclass(frozen=True, slots=True)
class _Target:
    target_role: str
    target_type: str
    document_name: str | None = None


class FixtureFilingSource:
    """Stored-products access for the filings one fixture captured."""

    def __init__(self, artifacts_root: Path | str, fixture_id: str) -> None:
        self.fixture_id = fixture_id
        self._by_accession: dict[str, list[FixtureDocumentPayload]] = {}
        for metadata, result in iter_case_results(artifacts_root, fixture_id):
            role = "primary" if metadata.key.source_document == "primary" else "exhibit"
            payload = FixtureDocumentPayload(
                document_name=metadata.key.source_document,
                target_role=role,
                target_type="",
                result=result,
                stamps=metadata.stamps,
            )
            self._by_accession.setdefault(metadata.key.accession, []).append(payload)

    def documents_for(
        self, accession: str, targets: tuple[_Target, ...] = ()
    ) -> tuple[FixtureDocumentPayload, ...]:
        """Every stored document for one accession, primary first."""
        payloads = list(self._by_accession.get(accession, ()))
        if targets:
            wanted = {
                (target.target_role, target.document_name)
                for target in targets
                if target.document_name
            }
            if wanted:
                payloads = [
                    item
                    for item in payloads
                    if (item.target_role, item.document_name) in wanted
                    or item.target_role == "primary"
                ]
        return tuple(sorted(payloads, key=lambda item: item.target_role != "primary"))

    def accessions(self) -> tuple[str, ...]:
        """Every accession the fixture captured, sorted."""
        return tuple(sorted(self._by_accession))
