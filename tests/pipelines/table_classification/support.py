"""Shared fixtures for table_classification pipeline tests."""

from __future__ import annotations

from edgar_sec.pipelines.table_classification.paths import ClassificationPaths
from edgar_sec.pipelines.table_classification.planner import (
    DocumentTargetRow,
    FilingRow,
    PlanRequest,
    ProfileApplicationRow,
    build_plan,
    read_plan,
)
from edgar_sec.pipelines.table_classification.worker import SourceDocumentPayload

HTML_10K = """<html><body>
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM 10-K</p>
<p>ACME CORPORATION</p>
<p>TABLE OF CONTENTS</p>
<table><tr><td>PART I</td><td>1</td></tr>
<tr><td>ITEM 1. BUSINESS</td><td>1</td></tr>
<tr><td>ITEM 2. PROPERTIES</td><td>14</td></tr></table>
<p>PART I</p>
<p>ITEM 1. BUSINESS</p>
<p>Acme is a leading provider of widgets and employs many people.</p>
<table><tr><td>Cash</td><td>100</td></tr><tr><td>Total assets</td><td>500</td></tr></table>
<p>SIGNATURES</p>
<p>Pursuant to the requirements of Section 13 of the Act, the registrant has duly caused this report to be signed.</p>
<table><tr><td>/s/ Jane Doe</td><td>Chief Executive Officer</td></tr></table>
</body></html>"""

EXHIBIT_TEXT = """<html><body>
<p>EXHIBIT 13</p>
<p>ANNUAL REPORT TO SECURITY HOLDERS</p>
<p>ACME CORPORATION</p>
<p>Consolidated statements of income and balance sheets follow.</p>
<table><tr><td>Cash</td><td>100</td></tr><tr><td>Total assets</td><td>500</td></tr></table>
</body></html>"""


def make_request(**overrides: object) -> PlanRequest:
    """One two-filing plan request in the contract's generic shape."""
    values: dict = {
        "registry_state": "registry:test-v1",
        "source_snapshot_id": "snap-test-1",
        "normalize_version": "normalize:test",
        "renderer_version": "renderer:test",
        "filings": (
            FilingRow("0000000001-26-000001", 1, "10-K", "2026-01-15", "B"),
            FilingRow("0000000002-26-000001", 2, "10-Q", "2026-02-15", "D"),
        ),
        "profile_application": (
            ProfileApplicationRow(
                "0000000001-26-000001",
                "balance_sheet",
                "family",
                "signature_competition",
            ),
        ),
        "document_targets": (
            DocumentTargetRow(
                "0000000001-26-000001",
                "primary",
                "10-K",
                False,
                "acme.htm",
                "expected",
                "render_to_txt",
            ),
            DocumentTargetRow(
                "0000000001-26-000001",
                "exhibit",
                "EX-13",
                True,
                "ex13.htm",
                "expected",
                "render_to_txt",
            ),
            DocumentTargetRow(
                "0000000002-26-000001",
                "primary",
                "10-Q",
                False,
                "quarter.htm",
                "expected",
                "render_to_txt",
            ),
        ),
        "created_at": "2026-11-15T00:00:00Z",
    }
    values.update(overrides)
    return PlanRequest(**values)


def make_plan(tmp_path, **overrides: object):  # noqa: ANN001, ANN202
    """Build and reload one plan under a tmp artifacts root."""
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    result = build_plan(make_request(**overrides), paths)
    return paths, read_plan(paths, result.plan_id)


class FakeSource:
    """In-memory FilingSource double keyed by accession."""

    def __init__(self, payloads: dict[str, tuple[SourceDocumentPayload, ...]]) -> None:
        self._payloads = payloads

    def documents_for(self, accession, targets):  # noqa: ANN001, ANN202
        """Payloads for one accession, empty when unacquired."""
        return self._payloads.get(accession, ())


def primary_payload(
    name: str = "acme.htm", text: str = HTML_10K
) -> SourceDocumentPayload:
    """One primary payload carrying the HTML 10-K fixture."""
    return SourceDocumentPayload(
        document_name=name,
        target_role="primary",
        target_type="10-K",
        raw=text.encode(),
    )
