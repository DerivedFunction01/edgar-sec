"""Per-vintage taxonomy archive: official-release declarations in parquet slices.

One slice per (taxonomy, version), derived from the published releases
by tools/build_taxonomy_archive.py. The resolver answers for a namespace
URI's own vintage: no slice or no row merges nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
import json
import re

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration

# Canonical qname prefix per archived taxonomy.
TAXONOMY_PREFIXES: dict[str, str] = {
    "us-gaap": "us-gaap",
    "dei": "dei",
    "srt": "srt",
    "ecd": "ecd",
    "cyd": "cyd",
    "ifrs": "ifrs-full",
}

# The slice union the retired standard_item_types.json carried: the
# reproduction baseline for callers with no filing vintage in hand.
CURRENT_SLICES: tuple[tuple[str, str], ...] = (
    ("us-gaap", "2026"),
    ("dei", "2024"),
    ("srt", "2024"),
    ("ecd", "2024"),
    ("cyd", "2024"),
)

_DATED = re.compile(r"^(\d{4})-\d{2}-\d{2}$")
_FASB = re.compile(r"^https?://(?:www\.)?fasb\.org/(us-gaap|srt)/([^/]+)$")
_SEC = re.compile(r"^https?://xbrl\.sec\.gov/(dei|ecd|cyd)/([^/]+)$")
_XBRL_US = re.compile(r"^https?://(?:taxonomies\.)?xbrl\.us/(us-gaap)/([^/]+)$")
_IFRS = re.compile(r"^https?://xbrl\.ifrs\.org/taxonomy/([^/]+)/ifrs-full$")


def _annual_version(token: str) -> str:
    """Annual version for a namespace token (dated forms fold to the year)."""
    dated = _DATED.match(token)
    return dated.group(1) if dated else token


def namespace_key(namespace_uri: str) -> tuple[str, str] | None:
    """(Taxonomy, version) a namespace URI names, or None when unrecognized."""
    for pattern in (_FASB, _SEC, _XBRL_US):
        match = pattern.match(namespace_uri)
        if match:
            return match.group(1), _annual_version(match.group(2))
    match = _IFRS.match(namespace_uri)
    if match:
        return "ifrs", match.group(1)
    return None


def slice_path(taxonomy: str, version: str) -> Path:
    """Archive parquet path for one (taxonomy, version) slice."""
    return (
        resolve_xbrl_paths().default_taxonomy_archive_dir
        / taxonomy
        / f"{version}.parquet"
    )


def slice_versions(taxonomy: str) -> tuple[str, ...]:
    """Versions archived for a taxonomy, sorted."""
    directory = resolve_xbrl_paths().default_taxonomy_archive_dir / taxonomy
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.stem for path in directory.glob("*.parquet")))


@lru_cache(maxsize=None)
def load_slice(taxonomy: str, version: str) -> tuple[ConceptDeclaration, ...]:
    """All declarations in one archive slice; empty when no slice exists."""
    path = slice_path(taxonomy, version)
    if not path.is_file():
        return ()
    rows = pq.read_table(path).to_pylist()
    return tuple(
        ConceptDeclaration(
            concept_qname=row["concept_qname"],
            name=row["name"],
            period_type=row["period_type"],
            balance=row["balance"],
            substitution_group=row["substitution_group"],
            item_type=row["item_type"],
        )
        for row in rows
    )


def slice_table(
    taxonomy: str, version: str, prefix: str | None = None
) -> dict[str, str]:
    """Qname -> item-type table for one slice, under a filing's prefix."""
    bound = prefix or TAXONOMY_PREFIXES[taxonomy]
    return {
        f"{bound}:{declaration.name}": declaration.item_type
        for declaration in load_slice(taxonomy, version)
        if declaration.item_type is not None
    }


def table_for_namespaces(namespaces: Mapping[str, str]) -> dict[str, str]:
    """Item-type table for exactly the vintages a namespace map declares.

    Prefixes whose namespace is unrecognized, or whose vintage has no
    archive slice, contribute nothing.
    """
    table: dict[str, str] = {}
    for prefix, uri in namespaces.items():
        key = namespace_key(uri)
        if key is None:
            continue
        table.update(slice_table(key[0], key[1], prefix))
    return table


def current_table() -> dict[str, str]:
    """The current-vintage union table (the retired JSON's exact content)."""
    table: dict[str, str] = {}
    for taxonomy, version in CURRENT_SLICES:
        table.update(slice_table(taxonomy, version))
    return table


def bundle_namespaces(bundle_dir: Path | str) -> dict[str, str]:
    """Prefix -> namespace URI map captured in a bundle's namespaces.json.

    Written at bundle generation from the filing instance; returns an
    empty map when the bundle carries no captured map.
    """
    path = Path(bundle_dir) / "namespaces.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(prefix): str(uri) for prefix, uri in data.items()}
