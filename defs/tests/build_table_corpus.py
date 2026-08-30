"""One-off builder for the tracked validated table corpus.

This script intentionally reads local scratch/source files and is never called
by pytest. Run it again only after manually reviewing new converter output.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from bs4 import BeautifulSoup

from defs.storage import pa, write_table_atomic
from defs.tables import convert_html_tables_to_ascii

ROOT = Path(__file__).parents[2]
DEFAULT_OUTPUT = ROOT / "defs/tests/fixtures/tables/validated_table_corpus.parquet"
SOURCES = {
    "apple_2025": ROOT
    / "phases/025_webpage_storage/scratch/multi_filing_eval/cache/aapl-20250927.htm",
    "jpmorgan_2025": ROOT
    / "phases/025_webpage_storage/scratch/multi_filing_eval/cache/jpm-20251231.htm",
    "jnj_2025": ROOT
    / "phases/025_webpage_storage/scratch/jnj_2025_10k/jnj-20251228.htm",
    "berry_2008": ROOT
    / "phases/025_webpage_storage/scratch/joint_utility_filings/berry_plastics_2008_10k_39ciks/primary_document.htm",
    "kellogg_2003": ROOT
    / "phases/025_webpage_storage/scratch/inspected_filings/55067_2003_0000950124-03-000647/k74347e10vk.htm",
}


def build(output: Path) -> int:
    records: list[dict[str, str]] = []
    for corpus, source in SOURCES.items():
        raw = source.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        soup = BeautifulSoup(raw, "lxml")
        for element in soup(
            ["head", "script", "style", "meta", "noscript", "ix:hidden", "ix:header"]
        ):
            element.decompose()
        for number, table in enumerate(soup.find_all("table"), start=1):
            html = str(table)
            records.append(
                {
                    "corpus": corpus,
                    "table_id": f"{corpus}_table_{number:04d}",
                    "source_sha256": source_hash,
                    "source_path": str(source.relative_to(ROOT)),
                    "html": html,
                    "expected": convert_html_tables_to_ascii(html),
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({key: [record[key] for record in records] for key in records[0]})
    write_table_atomic(table, output, expected_rows=len(records))
    print(f"wrote {len(records)} tables to {output}")
    return len(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output)
