"""Exact synthetic and threshold-based validated table corpus tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from defs.runtime.paths import resolve_paths
from defs.storage import DatasetSpec, pa, read_records
from defs.tables import convert_html_tables_to_ascii
from defs.testing.goldens import compare_golden_value

FIXTURES = Path(__file__).parent / "fixtures" / "tables"
CORPUS_PATH = FIXTURES / "validated_table_corpus.parquet"
CORPUS_SCHEMA = pa.schema(
    [
        ("corpus", pa.string()),
        ("table_id", pa.string()),
        ("source_sha256", pa.string()),
        ("source_path", pa.string()),
        ("html", pa.string()),
        ("expected", pa.string()),
    ]
)


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


@pytest.mark.parametrize(
    "name",
    [
        "split_currency_amounts",
        "rowspan_headers",
        "section_headers",
        "bullet_list_layout",
        "toc_unwrap_layout",
        "sparse_footnotes",
        "year_stub_with_text",
    ],
)
def test_synthetic_table_golden(name: str) -> None:
    input_path = FIXTURES / "synthetic" / f"{name}.html"
    expected_path = FIXTURES / "synthetic" / f"{name}.expected"
    actual = convert_html_tables_to_ascii(input_path.read_text(encoding="utf-8"))
    assert actual == expected_path.read_text(encoding="utf-8")


def test_manually_validated_jnj_derivatives_table() -> None:
    records = read_records(
        CORPUS_PATH,
        "parquet",
        spec=DatasetSpec(
            name="validated_table_corpus",
            schema_version="1",
            key_field="table_id",
            arrow_schema=CORPUS_SCHEMA,
            required_fields=tuple(CORPUS_SCHEMA.names),
        ),
    )
    record = next(item for item in records if item["table_id"] == "jnj_2025_table_0108")
    assert "Hedged items" in record["expected"]
    assert "Derivatives designated as hedging instruments" in record["expected"]
    assert "December 28, 2025" in record["expected"]


def _validated_corpus(corpus: str) -> tuple[int, int, int, list[str], Path]:
    records = read_records(
        CORPUS_PATH,
        "parquet",
        spec=DatasetSpec(
            name="validated_table_corpus",
            schema_version="1",
            key_field="table_id",
            arrow_schema=CORPUS_SCHEMA,
            required_fields=tuple(CORPUS_SCHEMA.names),
        ),
    )
    selected = [record for record in records if record["corpus"] == corpus]
    report_root = (
        resolve_paths().test_run_root("defs", "table-goldens", _run_id()) / corpus
    )
    report_root.mkdir(parents=True, exist_ok=True)
    matched = divergent = invalid = 0
    divergent_ids: list[str] = []
    for record in selected:
        fixture_id = record["table_id"]
        try:
            actual = convert_html_tables_to_ascii(record["html"])
            if compare_golden_value(
                actual,
                record["expected"],
                report_root,
                fixture_id,
                {
                    "source_path": record["source_path"],
                    "source_sha256": record["source_sha256"],
                },
            ):
                matched += 1
            else:
                divergent += 1
                divergent_ids.append(fixture_id)
        except (KeyError, TypeError, ValueError) as exc:
            invalid += 1
            divergent_ids.append(fixture_id)
            (report_root / fixture_id).mkdir(parents=True, exist_ok=True)
            (report_root / fixture_id / "metadata.json").write_text(
                f'{{"fixture_id": "{fixture_id}", "error": "{exc}"}}\n',
                encoding="utf-8",
            )
    comparable = matched + divergent
    rate = matched / comparable if comparable else 0.0
    summary = {
        "corpus": corpus,
        "threshold": 0.95,
        "tables_checked": len(selected),
        "matched": matched,
        "diverged": divergent,
        "invalid": invalid,
        "match_rate": rate,
        "divergent_table_ids": divergent_ids,
    }
    (report_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"TABLE CORPUS: {'PASS' if invalid == 0 and comparable and rate >= 0.95 else 'FAIL'}\n"
        f"Corpus: {corpus}\nTables checked: {len(selected)}\n"
        f"Matched: {matched}\nDiverged: {divergent}\nInvalid: {invalid}\n"
        f"Match rate: {rate:.2%}\nDivergence report: {report_root}"
    )
    return matched, divergent, invalid, divergent_ids, report_root


@pytest.mark.parametrize(
    "corpus",
    ["apple_2025", "jnj_2025", "jpmorgan_2025", "berry_2008", "kellogg_2003"],
)
def test_validated_table_corpus(corpus: str) -> None:
    matched, divergent, invalid, divergent_ids, report_root = _validated_corpus(corpus)
    comparable = matched + divergent
    assert comparable > 0, f"{corpus} has no tables: {report_root}"
    assert invalid == 0, f"{corpus} has invalid tables: {report_root}"
    assert matched / comparable >= 0.95, (
        f"{corpus} matched {matched}/{comparable}; "
        f"divergences: {divergent_ids}; report: {report_root}"
    )
