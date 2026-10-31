"""Build the per-vintage taxonomy archive from the official releases.

Downloads each release's core element schema into an out-of-repo cache,
parses its declarations with the repo's schema parser, and writes one
parquet slice per (taxonomy, version) under the taxonomy archive dir.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from edgar_sec.engine.xbrl.parsing.linkbase_parser import parse_schema_declarations
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.taxonomy.archive import TAXONOMY_PREFIXES
from edgar_sec.engine.xbrl.taxonomy.item_types import item_type_local
from edgar_sec.foundation.runtime.env import get_env

_TARGET_NAMESPACE = re.compile(rb"""targetNamespace=["']([^"']+)["']""")

_FASB = "https://xbrl.fasb.org"
_SEC = "https://xbrl.sec.gov"
_IFRS_DATES = (
    "2014-03-05",
    "2015-03-11",
    "2016-03-31",
    "2017-03-09",
    "2018-03-16",
    "2019-03-27",
    "2020-03-16",
    "2021-03-24",
    "2022-03-24",
    "2023-03-23",
    "2024-03-27",
    "2025-03-27",
)


def _releases() -> tuple[tuple[str, str, str], ...]:
    """(Taxonomy, version, core-schema URL) for every published release."""
    releases: list[tuple[str, str, str]] = [
        (
            "us-gaap",
            "2009",
            "http://taxonomies.xbrl.us/us-gaap/2009/elts/us-gaap-2009-01-31.xsd",
        )
    ]
    for year in range(2011, 2027):
        suffix = f"-{year}-01-31" if year <= 2021 else f"-{year}"
        releases.append(
            ("us-gaap", str(year), f"{_FASB}/us-gaap/{year}/elts/us-gaap{suffix}.xsd")
        )
    for year in range(2018, 2027):
        suffix = f"-{year}-01-31" if year <= 2021 else f"-{year}"
        releases.append(("srt", str(year), f"{_FASB}/srt/{year}/elts/srt{suffix}.xsd"))
    for version in ("2011", "2012", "2013", "2014", "2018", "2019", "2020"):
        releases.append(
            ("dei", version, f"{_SEC}/dei/{version}/dei-{version}-01-31.xsd")
        )
    for version in ("2021", "2021q4", "2022", "2022q4", "2023", "2024", "2025", "2026"):
        releases.append(("dei", version, f"{_SEC}/dei/{version}/dei-{version}.xsd"))
    for version in ("2022", "2022q4", "2023", "2024", "2025", "2026"):
        releases.append(("ecd", version, f"{_SEC}/ecd/{version}/ecd-{version}.xsd"))
    for year in (2024, 2025, 2026):
        releases.append(("cyd", str(year), f"{_SEC}/cyd/{year}/cyd-{year}.xsd"))
    for date in _IFRS_DATES:
        releases.append(
            (
                "ifrs",
                date,
                f"https://xbrl.ifrs.org/taxonomy/{date}/full_ifrs/full_ifrs-cor_{date}.xsd",
            )
        )
    return tuple(releases)


_SCHEMA = pa.schema(
    [
        ("taxonomy", pa.string()),
        ("version", pa.string()),
        ("namespace_uri", pa.string()),
        ("concept_qname", pa.string()),
        ("name", pa.string()),
        ("item_type", pa.string()),
        ("period_type", pa.string()),
        ("balance", pa.string()),
        ("substitution_group", pa.string()),
    ]
)


def _fetch(url: str, cache_path: Path) -> bytes:
    """Read a release schema from the cache, downloading it if missing."""
    if cache_path.is_file():
        return cache_path.read_bytes()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": get_env("SEC_USER_AGENT") or "edgar-sec-archive/1.0"},
    )
    with urllib.request.urlopen(request) as response:
        payload = response.read()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(payload)
    return payload


def _namespace_of(xsd: bytes) -> str:
    """The schema's targetNamespace, read from its root element."""
    match = _TARGET_NAMESPACE.search(xsd[:262144])
    return match.group(1).decode("utf-8") if match else ""


def build(cache_dir: Path, out_dir: Path) -> int:
    """Derive every archive slice; returns the total archived row count."""
    total = 0
    for taxonomy, version, url in _releases():
        prefix = TAXONOMY_PREFIXES[taxonomy]
        payload = _fetch(url, cache_dir / "xsd" / taxonomy / f"{version}.xsd")
        namespace = _namespace_of(payload)
        rows = [
            {
                "taxonomy": taxonomy,
                "version": version,
                "namespace_uri": namespace,
                "concept_qname": declaration.concept_qname,
                "name": declaration.name,
                "item_type": declaration.item_type,
                "period_type": declaration.period_type,
                "balance": declaration.balance,
                "substitution_group": declaration.substitution_group,
            }
            for declaration in parse_schema_declarations(payload, target_prefix=prefix)
            if (local := item_type_local(declaration.item_type)) is not None
            and local.endswith("ItemType")
        ]
        rows.sort(key=lambda row: row["concept_qname"])
        slice_path = out_dir / taxonomy / f"{version}.parquet"
        slice_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=_SCHEMA), slice_path)
        total += len(rows)
        print(f"{taxonomy} {version}: {len(rows)} rows, ns={namespace}, src={url}")
    return total


def main() -> int:
    """Build the archive into the taxonomy directory (or --out-dir)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / "workspace" / "xbrl-triage" / "taxonomy-archive-src",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=resolve_xbrl_paths().default_taxonomy_archive_dir,
    )
    args = parser.parse_args()
    total = build(args.cache_dir, args.out_dir)
    print(f"wrote {total} rows -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
