"""Era attribution over the taxonomy archive slices.

Dates every concept in the solver's vocabulary, and every token the
decomposer derives from its name, to the first archived era carrying
it, and renders the per-era record.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import re
import sys

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.normalize.decomposer import split_camel_case
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.taxonomy.archive import CURRENT_SLICES, TAXONOMY_PREFIXES
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_text

_YEAR = re.compile(r"^(\d{4})")
_DATED = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_QUARTER = re.compile(r"^(\d{4})q([1-4])$")


def era_year(version: str) -> int:
    """Calendar year a slice version belongs to; versions fold to it."""
    match = _YEAR.match(version)
    if match is None:
        raise ValueError(f"version carries no leading year: {version!r}")
    return int(match.group(1))


def era_label(version: str) -> str:
    """Era label for a slice version: its calendar year, as text."""
    return str(era_year(version))


def _version_order(version: str) -> tuple[int, int, int, int]:
    """Chronological sort key for one taxonomy's slice versions."""
    dated = _DATED.match(version)
    if dated:
        return (int(dated.group(1)), int(dated.group(2)), int(dated.group(3)), 0)
    quarter = _QUARTER.match(version)
    if quarter:
        return (int(quarter.group(1)), 3 * int(quarter.group(2)), 28, 1)
    return (era_year(version), 1, 1, 0)


@dataclass(frozen=True)
class SliceData:
    """One archive slice reduced to its concept and token sets."""

    taxonomy: str
    version: str
    era: str
    qnames: frozenset[str]
    tokens: frozenset[str]


def _load_slice(task: tuple[str, str, str]) -> SliceData:
    """Load one slice's qname set and derived token set from parquet."""
    taxonomy, version, path = task
    table = pq.read_table(path, columns=["concept_qname", "name"])
    qnames = frozenset(table.column("concept_qname").to_pylist())
    tokens = frozenset(
        token
        for name in table.column("name").to_pylist()
        for token in split_camel_case(name)
    )
    return SliceData(
        taxonomy=taxonomy,
        version=version,
        era=era_label(version),
        qnames=qnames,
        tokens=tokens,
    )


def discover_slices(archive_dir: Path) -> list[tuple[str, str, Path]]:
    """(Taxonomy, version, path) for every slice under an archive dir."""
    found: list[tuple[str, str, Path]] = []
    for taxonomy in sorted(TAXONOMY_PREFIXES):
        directory = archive_dir / taxonomy
        if not directory.is_dir():
            continue
        versions = sorted(
            (path.stem for path in directory.glob("*.parquet")), key=_version_order
        )
        found.extend(
            (taxonomy, version, directory / f"{version}.parquet")
            for version in versions
        )
    return found


def load_slices(archive_dir: Path, workers: int) -> tuple[SliceData, ...]:
    """Load every slice under an archive dir, pooled across processes.

    Per-slice work is independent and the result is sorted after the
    pool drains, so the worker count cannot change any set.
    """
    tasks = [
        (taxonomy, version, str(path))
        for taxonomy, version, path in discover_slices(archive_dir)
    ]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            loaded = list(pool.map(_load_slice, tasks))
    else:
        loaded = [_load_slice(task) for task in tasks]
    return tuple(
        sorted(
            loaded, key=lambda slice_: (slice_.taxonomy, _version_order(slice_.version))
        )
    )


@dataclass(frozen=True)
class Attribution:
    """First-appearance dating of one vocabulary over ordered eras."""

    horizon_era: str
    core: frozenset[str]
    additions: dict[str, frozenset[str]]
    removals: dict[str, frozenset[str]]
    era_unions: dict[str, frozenset[str]]

    @property
    def latest(self) -> frozenset[str]:
        """The vocabulary as of the last era."""
        return self.era_unions[max(self.era_unions, key=int)]

    @property
    def universe(self) -> frozenset[str]:
        """Every item that ever appeared, across all eras."""
        return frozenset().union(*self.era_unions.values())


def attribute(era_unions: list[tuple[str, frozenset[str]]]) -> Attribution:
    """Date each item to the first era whose union carries it.

    `era_unions` is chronological (era label, that era's full set);
    the first era's union is the horizon core by definition.
    """
    merged: dict[str, frozenset[str]] = {}
    for era, union in era_unions:
        merged[era] = merged.get(era, frozenset()) | union
    ordered = sorted(merged, key=int)
    core = merged[ordered[0]]
    seen = core
    additions: dict[str, frozenset[str]] = {}
    removals: dict[str, frozenset[str]] = {}
    previous = core
    for era in ordered[1:]:
        union = merged[era]
        additions[era] = union - seen
        removals[era] = previous - union
        seen |= union
        previous = union
    return Attribution(
        horizon_era=ordered[0],
        core=core,
        additions=additions,
        removals=removals,
        era_unions=merged,
    )


def _era_unions(
    slices: tuple[SliceData, ...], field: str
) -> list[tuple[str, frozenset[str]]]:
    """Chronological (era, union) pairs for one slice field."""
    unions: dict[str, frozenset[str]] = {}
    for slice_ in slices:
        unions[slice_.era] = unions.get(slice_.era, frozenset()) | getattr(
            slice_, field
        )
    return [(era, unions[era]) for era in sorted(unions, key=int)]


@dataclass(frozen=True)
class TaxonomyReport:
    """Era attribution for one taxonomy's concepts and tokens."""

    taxonomy: str
    versions: tuple[str, ...]
    concepts: Attribution
    tokens: Attribution
    current_concepts: frozenset[str]
    current_tokens: frozenset[str]


@dataclass(frozen=True)
class EraReport:
    """The whole study: per-taxonomy reports plus union headlines."""

    slice_count: int
    workers: int
    taxonomies: tuple[TaxonomyReport, ...]
    today_concepts_by_era: dict[str, int]
    today_concept_core: int
    today_tokens_by_era: dict[str, int]
    today_token_core: int
    full_concepts_by_era: dict[str, int]

    @property
    def today_concept_total(self) -> int:
        """Concepts in today's solver vocabulary."""
        return sum(self.today_concepts_by_era.values())

    @property
    def today_token_total(self) -> int:
        """Tokens in today's solver vocabulary."""
        return sum(self.today_tokens_by_era.values())


def build_report(
    archive_dir: Path,
    workers: int,
    current_slices: tuple[tuple[str, str], ...] = CURRENT_SLICES,
) -> EraReport:
    """Run the full attribution over an archive directory."""
    slices = load_slices(archive_dir, workers)
    by_key = {(slice_.taxonomy, slice_.version): slice_ for slice_ in slices}
    by_taxonomy: dict[str, list[SliceData]] = {}
    for slice_ in slices:
        by_taxonomy.setdefault(slice_.taxonomy, []).append(slice_)

    reports: list[TaxonomyReport] = []
    today_concepts_by_era: dict[str, int] = {}
    full_concepts_by_era: dict[str, int] = {}
    today_concept_core = 0
    for taxonomy in sorted(by_taxonomy):
        group = tuple(by_taxonomy[taxonomy])
        concepts = attribute(_era_unions(group, "qnames"))
        tokens = attribute(_era_unions(group, "tokens"))
        current_version = dict(current_slices).get(taxonomy)
        current = by_key.get((taxonomy, current_version)) if current_version else None
        current_concepts = current.qnames if current else frozenset()
        current_tokens = current.tokens if current else frozenset()
        reports.append(
            TaxonomyReport(
                taxonomy=taxonomy,
                versions=tuple(slice_.version for slice_ in group),
                concepts=concepts,
                tokens=tokens,
                current_concepts=current_concepts,
                current_tokens=current_tokens,
            )
        )
        first_era = {
            item: era for era, added in concepts.additions.items() for item in added
        }
        for item in concepts.core:
            first_era[item] = concepts.horizon_era
        for item in concepts.universe:
            era = first_era[item]
            full_concepts_by_era[era] = full_concepts_by_era.get(era, 0) + 1
        for item in current_concepts:
            era = first_era[item]
            today_concepts_by_era[era] = today_concepts_by_era.get(era, 0) + 1
        today_concept_core += len(current_concepts & concepts.core)

    today_tokens_by_era: dict[str, int] = {}
    today_token_core = 0
    global_unions: dict[str, frozenset[str]] = {}
    for report in reports:
        for era, union in report.tokens.era_unions.items():
            global_unions[era] = global_unions.get(era, frozenset()) | union
    global_attr = attribute(
        [(era, global_unions[era]) for era in sorted(global_unions, key=int)]
    )
    token_first_era = {token: global_attr.horizon_era for token in global_attr.core}
    token_first_era.update(
        {token: era for era, added in global_attr.additions.items() for token in added}
    )
    for report in reports:
        for token in report.current_tokens:
            era = token_first_era[token]
            today_tokens_by_era[era] = today_tokens_by_era.get(era, 0) + 1
    today_token_core = len(
        frozenset().union(*(report.current_tokens for report in reports))
        & frozenset().union(*(report.tokens.core for report in reports))
    )
    return EraReport(
        slice_count=len(slices),
        workers=workers,
        taxonomies=tuple(reports),
        today_concepts_by_era=today_concepts_by_era,
        today_concept_core=today_concept_core,
        today_tokens_by_era=today_tokens_by_era,
        today_token_core=today_token_core,
        full_concepts_by_era=full_concepts_by_era,
    )


def _share(part: int, whole: int) -> str:
    """A count as a percentage of a total, one decimal."""
    return f"{100.0 * part / whole:.1f}%" if whole else "—"


def _additions_cell(attribution: Attribution) -> str:
    """Compact per-era additions for one attribution, era: count."""
    cells = [f"{attribution.horizon_era}: {len(attribution.core)} (core)"]
    cells.extend(
        f"{era}: {len(added)}"
        for era, added in sorted(
            attribution.additions.items(), key=lambda kv: int(kv[0])
        )
    )
    return " · ".join(cells)


def render_record(report: EraReport) -> str:
    """Render the study record: headline tables, detail, caveats."""
    lines: list[str] = [
        "# Taxonomy era attribution — run record",
        "",
        f"- Archive: {report.slice_count} slices across "
        f"{len(report.taxonomies)} taxonomies; slice sweep pooled over "
        f"{report.workers} workers.",
        "- Population: today's solver vocabulary is the `CURRENT_SLICES` union; "
        "an item's era is the first archived era carrying it, versions folded "
        "to their calendar year.",
        "",
        "## Headline — today's vocabulary by era of first appearance",
        "",
        "| Era | Concepts | Tokens |",
        "| --- | ---: | ---: |",
    ]
    eras = sorted(
        set(report.today_concepts_by_era) | set(report.today_tokens_by_era), key=int
    )
    for era in eras:
        lines.append(
            f"| {era} | {report.today_concepts_by_era.get(era, 0)} "
            f"| {report.today_tokens_by_era.get(era, 0)} |"
        )
    lines.append(
        f"| **Total** | **{report.today_concept_total}** "
        f"| **{report.today_token_total}** |"
    )
    lines.extend(
        [
            "",
            f"- Era-less core in today's vocabulary: {report.today_concept_core} "
            f"concepts ({_share(report.today_concept_core, report.today_concept_total)}), "
            f"{report.today_token_core} tokens "
            f"({_share(report.today_token_core, report.today_token_total)}) — "
            "present at their taxonomy's archive horizon.",
            f"- Postdating the global horizon: "
            f"{report.today_concept_total - report.today_concepts_by_era.get(min(eras, key=int), 0)} "
            "of today's concepts first appear after the earliest era.",
            "",
            "## Full archive union — concepts ever carried, by era",
            "",
            "| Era | Concepts |",
            "| --- | ---: |",
        ]
    )
    for era in sorted(report.full_concepts_by_era, key=int):
        lines.append(f"| {era} | {report.full_concepts_by_era[era]} |")
    lines.extend(
        [
            "",
            "## Per-taxonomy concept attribution",
            "",
            "| Taxonomy | Horizon | Slices | Latest | Today | Additions by era |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for taxonomy in report.taxonomies:
        concepts = taxonomy.concepts
        lines.append(
            f"| {taxonomy.taxonomy} | {concepts.horizon_era} "
            f"| {len(taxonomy.versions)} | {len(concepts.latest)} "
            f"| {len(taxonomy.current_concepts)} | {_additions_cell(concepts)} |"
        )
    lines.extend(
        [
            "",
            "## Survivorship and removals — concepts, per era",
            "",
            "| Taxonomy | Era | Added | Survive to latest | Survive to today "
            "| Removed entering era |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for taxonomy in report.taxonomies:
        concepts = taxonomy.concepts
        rows: list[tuple[str, frozenset[str], int]] = [
            (concepts.horizon_era, concepts.core, 0)
        ]
        rows.extend(
            (era, concepts.additions[era], len(concepts.removals.get(era, ())))
            for era in sorted(concepts.additions, key=int)
        )
        for era, added, removed in rows:
            lines.append(
                f"| {taxonomy.taxonomy} | {era} | {len(added)} "
                f"| {len(added & concepts.latest)} "
                f"| {len(added & taxonomy.current_concepts)} | {removed} |"
            )
    single_slice = [
        taxonomy.taxonomy
        for taxonomy in report.taxonomies
        if len(taxonomy.versions) == 1
    ]
    horizons = " · ".join(
        f"{taxonomy.taxonomy} {taxonomy.concepts.horizon_era}"
        for taxonomy in report.taxonomies
    )
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            f"- Horizons differ per taxonomy ({horizons}); the core is core at "
            "the archive horizon, not timeless — earlier releases some "
            "taxonomies published are not in the archive.",
            "- Concept identity is the exact qname: a renamed concept reads as "
            "a removal plus an addition, and removals are slice-to-slice "
            "disappearances under that identity.",
        ]
    )
    if single_slice:
        lines.append(
            "- Single-slice taxonomies ("
            + ", ".join(f"`{name}`" for name in single_slice)
            + ") carry no internal era structure: their whole vocabulary is "
            "horizon core by construction and is flagged here, not merged "
            "silently into the headline."
        )
    lines.append(
        "- The FASB proposed update for consideration payable to a customer "
        "(proposed Topic 606 ASU) is not counted: no published slice carries "
        "it. When one does, this tool attributes its elements to their era "
        "with no new code — the forward direction of the claim this record "
        "measures backward."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: run the attribution and write or print the record."""
    parser = argparse.ArgumentParser(
        description="Attribute the solver's vocabulary to taxonomy eras."
    )
    parser.add_argument("--archive-dir", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    archive_dir = args.archive_dir or resolve_xbrl_paths().default_taxonomy_archive_dir
    workers = args.workers or derive_resources().workers
    record = render_record(build_report(archive_dir, workers))
    if args.out is not None:
        atomic_write_text(args.out, record)
    else:
        print(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
