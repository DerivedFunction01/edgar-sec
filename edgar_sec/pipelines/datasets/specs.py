"""Per-dataset specs for the adopted data-research sets.

A spec names the set's surface builder, bulk-store source id, loadable
members, and submission member. Schemas are not pinned: the store loads
every column as text, so a spec never names columns.
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

from edgar_sec.infra.storage.dag.spec import RelationSpec


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """One adopted dataset set and its load contract."""

    set_id: str
    source_id: str
    builder: str
    member_prefix: str
    submission_member: str
    excluded_members: tuple[str, ...] = ()
    member_suffix: str = ".tsv"

    def relation_for(self, member_name: str) -> str | None:
        """Store relation for one archive member, or None when not loaded."""
        base = member_name.rsplit("/", 1)[-1]
        if not base.lower().endswith(self.member_suffix):
            return None
        if base in self.excluded_members:
            return None
        if self.member_prefix and not member_name.startswith(self.member_prefix):
            return None
        stem = base[: -len(self.member_suffix)].lower()
        if self.set_id == "nmfp":
            stem = stem.removeprefix("nmfp_")
        return f"{self.set_id}_{stem}"

    def is_submission_member(self, member_name: str) -> bool:
        """Whether a member is the set's submission table."""
        return member_name.rsplit("/", 1)[-1] == self.submission_member


BDC_SPEC = DatasetSpec(
    set_id="bdc",
    source_id="bdc_datasets",
    builder="bdc_dataset_url",
    member_prefix="datasets/",
    submission_member="sub.tsv",
    excluded_members=("soi.tsv",),
)
NMFP_SPEC = DatasetSpec(
    set_id="nmfp",
    source_id="nmfp_datasets",
    builder="nmfp_dataset_url",
    member_prefix="",
    submission_member="NMFP_SUBMISSION.tsv",
)
MFRR_SPEC = DatasetSpec(
    set_id="mfrr",
    source_id="mfrr_datasets",
    builder="mfrr_dataset_url",
    member_prefix="",
    submission_member="sub.tsv",
)
FSDS_SPEC = DatasetSpec(
    set_id="fsds",
    source_id="fsds_datasets",
    builder="fsds_dataset_url",
    member_prefix="",
    submission_member="sub.txt",
    member_suffix=".txt",
)

DATASET_SPECS: dict[str, DatasetSpec] = {
    spec.set_id: spec for spec in (BDC_SPEC, NMFP_SPEC, MFRR_SPEC, FSDS_SPEC)
}

BDC_POPULATION_SOURCE_ID = "bdc_report"
BDC_POPULATION_YEARS = 3


def spec_for(set_id: str) -> DatasetSpec:
    """Return the spec for one adopted set; unknown sets are refused."""
    spec = DATASET_SPECS.get(str(set_id).strip())
    if spec is None:
        raise ValueError(
            f"unknown dataset set {set_id!r}; adopted sets: {sorted(DATASET_SPECS)}"
        )
    return spec


_VARCHAR = pa.string()
_VINTAGES_SCHEMA = pa.schema(
    [
        ("set_id", _VARCHAR, False),
        ("vintage", _VARCHAR, False),
        ("archive_sha", _VARCHAR, False),
        ("source_url", _VARCHAR, False),
        ("loaded_at", _VARCHAR, False),
    ]
)
_VINTAGE_TABLES_SCHEMA = pa.schema(
    [
        ("set_id", _VARCHAR, False),
        ("vintage", _VARCHAR, False),
        ("archive_sha", _VARCHAR, False),
        ("relation", _VARCHAR, False),
        ("member", _VARCHAR, False),
        ("source_rows", pa.int64(), False),
        ("loaded_rows", pa.int64(), False),
    ]
)
_POPULATION_SCHEMA = pa.schema(
    [
        ("cik", _VARCHAR, False),
        ("registrant_name", _VARCHAR),
        ("file_number", _VARCHAR),
        ("city", _VARCHAR),
        ("state", _VARCHAR),
        ("zip_code", _VARCHAR),
        ("last_filing_date", _VARCHAR),
        ("last_filing_type", _VARCHAR),
        ("report_year", pa.int64(), False),
        ("loaded_at", _VARCHAR, False),
    ]
)

DATASET_RELATION_SPECS: dict[str, RelationSpec] = {
    spec.name: spec
    for spec in (
        RelationSpec(
            name="dataset_vintages",
            schema=_VINTAGES_SCHEMA,
            primary_key=("set_id", "vintage", "archive_sha"),
            merge_strategy="append",
            sort_order=("set_id", "vintage", "archive_sha"),
        ),
        RelationSpec(
            name="dataset_vintage_tables",
            schema=_VINTAGE_TABLES_SCHEMA,
            primary_key=("set_id", "vintage", "archive_sha", "relation"),
            merge_strategy="append",
            sort_order=("set_id", "vintage", "archive_sha", "relation"),
        ),
        RelationSpec(
            name="bdc_population",
            schema=_POPULATION_SCHEMA,
            primary_key=("cik", "report_year"),
            merge_strategy="append",
            sort_order=("cik", "report_year"),
        ),
    )
}


__all__ = [
    "BDC_POPULATION_SOURCE_ID",
    "BDC_POPULATION_YEARS",
    "BDC_SPEC",
    "DATASET_RELATION_SPECS",
    "DATASET_SPECS",
    "DatasetSpec",
    "FSDS_SPEC",
    "MFRR_SPEC",
    "NMFP_SPEC",
    "spec_for",
]
