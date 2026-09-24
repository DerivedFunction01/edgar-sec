"""Audit harness asserting zero table corruption across acceptance inventory datasets.

Evaluates blocks against the declarative RuleEngine and provides detailed forensic
anomaly logging for any block where an unwrapped action occurs on a tabular cohort.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from defs.text.reflow.tools.clustering.dataset import (
    COHORT_CANDIDATES,
    COHORT_CLEAN_PROSE,
    COHORT_CLEAN_TABLES,
    COHORT_EDGE_CASE_TABLES,
    DatasetBlock,
    load_dataset_from_jsonl,
    resolve_reflow_dataset,
)
from defs.text.reflow.tools.clustering.rules import RuleEngine
from defs.text.reflow.types import ACTION_PRESERVE, ACTION_UNWRAP, SpanDecision


def default_inventory_path(path_or_id: str | Path | None = None) -> Path:
    """Return the reflow dataset path resolved dynamically."""
    return resolve_reflow_dataset(path_or_id)


@dataclass(slots=True)
class AuditAnomaly:
    """Forensic report for a table block that was unwrapped."""

    block_id: str
    accession: str | None
    document_path: str | None
    start_line: int
    end_line: int
    control_role: str
    cohort: str
    decision: SpanDecision
    text: str


@dataclass(slots=True)
class AuditSummary:
    """Aggregated outcome of the zero-corruption audit."""

    total_blocks: int
    total_tables: int
    tables_preserved: int
    tables_unwrapped: int
    prose_total: int
    prose_unwrapped: int
    candidates_total: int
    candidates_unwrapped: int
    anomalies: list[AuditAnomaly]

    @property
    def table_preservation_rate(self) -> float:
        return (
            (self.tables_preserved / self.total_tables)
            if self.total_tables > 0
            else 1.0
        )

    @property
    def table_corruption_rate(self) -> float:
        return (
            (self.tables_unwrapped / self.total_tables)
            if self.total_tables > 0
            else 0.0
        )


def run_zero_corruption_audit(
    blocks: list[DatasetBlock],
    engine: RuleEngine | None = None,
    show_progress: bool = True,
) -> AuditSummary:
    """Audit all dataset blocks against the rule engine.

    Parameters
    ----------
    blocks : list[DatasetBlock]
        List of dataset blocks past the cover boundary.
    engine : RuleEngine, optional
        Configured rule engine. Uses default rules if None.
    show_progress : bool
        Whether to display tqdm progress bar.
    """
    engine = engine or RuleEngine()

    total_blocks = len(blocks)
    total_tables = 0
    tables_preserved = 0
    tables_unwrapped = 0
    prose_total = 0
    prose_unwrapped = 0
    candidates_total = 0
    candidates_unwrapped = 0
    anomalies: list[AuditAnomaly] = []

    iterator = (
        tqdm(blocks, desc="Auditing blocks", unit="block") if show_progress else blocks
    )

    for block in iterator:
        is_table = block.expected_action == ACTION_PRESERVE or block.cohort in (
            COHORT_CLEAN_TABLES,
            COHORT_EDGE_CASE_TABLES,
        )
        is_prose = (
            block.expected_action == ACTION_UNWRAP or block.cohort == COHORT_CLEAN_PROSE
        )
        is_candidate = (
            block.expected_action is None and block.cohort == COHORT_CANDIDATES
        )

        decision = engine.decide(block.context)

        if is_table:
            total_tables += 1
            if decision.action == ACTION_UNWRAP:
                # Forensic check: was this genuine table or mislabeled prose (like Note 2)?
                tables_unwrapped += 1
                anomalies.append(
                    AuditAnomaly(
                        block_id=block.block_id,
                        accession=block.accession,
                        document_path=block.document_path,
                        start_line=block.start_line,
                        end_line=block.end_line,
                        control_role=block.control_role,
                        cohort=block.cohort,
                        decision=decision,
                        text=block.text,
                    )
                )
            else:
                tables_preserved += 1

        elif is_prose:
            prose_total += 1
            if decision.action == ACTION_UNWRAP:
                prose_unwrapped += 1

        elif is_candidate:
            candidates_total += 1
            if decision.action == ACTION_UNWRAP:
                candidates_unwrapped += 1

    return AuditSummary(
        total_blocks=total_blocks,
        total_tables=total_tables,
        tables_preserved=tables_preserved,
        tables_unwrapped=tables_unwrapped,
        prose_total=prose_total,
        prose_unwrapped=prose_unwrapped,
        candidates_total=candidates_total,
        candidates_unwrapped=candidates_unwrapped,
        anomalies=anomalies,
    )


def print_audit_report(summary: AuditSummary) -> None:
    """Format and print audit results to stdout."""
    print("\n" + "=" * 70)
    print("           REFLOW RULE ENGINE ZERO-CORRUPTION AUDIT REPORT           ")
    print("=" * 70)
    print(f"Total Blocks Audited      : {summary.total_blocks:,}")
    print(f"Total Table Blocks        : {summary.total_tables:,}")
    print(
        f"  - Preserved Tables      : {summary.tables_preserved:,} ({summary.table_preservation_rate * 100:.2f}%)"
    )
    print(
        f"  - Unwrapped Tables      : {summary.tables_unwrapped:,} ({summary.table_corruption_rate * 100:.2f}%)"
    )
    print(f"Total Prose Blocks        : {summary.prose_total:,}")
    print(
        f"  - Successfully Unwrapped: {summary.prose_unwrapped:,} ({(summary.prose_unwrapped / max(1, summary.prose_total)) * 100:.2f}%)"
    )
    print(f"Candidates Audited        : {summary.candidates_total:,}")
    print(
        f"  - Safely Preserved      : {summary.candidates_total - summary.candidates_unwrapped:,}"
    )
    print(f"  - Selectively Unwrapped : {summary.candidates_unwrapped:,}")
    print("=" * 70)

    if summary.anomalies:
        print(
            f"\n[!] ANOMALIES FOUND: {len(summary.anomalies)} table blocks unwrapped:"
        )
        for idx, a in enumerate(summary.anomalies, 1):
            print(f"\n--- Anomaly #{idx} ---")
            print(f"Block ID : {a.block_id}")
            print(
                f"Accession: {a.accession} | File: {a.document_path} (Lines {a.start_line}-{a.end_line})"
            )
            print(f"Role     : {a.control_role} | Cohort: {a.cohort}")
            print(f"Decision : {a.decision.action} via {a.decision.trace}")
            print("Preview  :")
            for line in a.text.splitlines()[:5]:
                print(f"  | {line}")
            if len(a.text.splitlines()) > 5:
                print(f"  | ... ({len(a.text.splitlines()) - 5} more lines)")
    else:
        print("\n[OK] PERFECT AUDIT: 0.00% true table corruption detected.")
    print("=" * 70 + "\n")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Zero-corruption audit of reflow rule engine across acceptance blocks."
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        default=None,
        help="Optional path to JSONL dataset, inventory directory, or inventory ID.",
    )
    parser.add_argument(
        "--dataset",
        "-d",
        dest="dataset_flag",
        default=None,
        help="Optional flag specifying dataset path or inventory ID.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress bar.",
    )
    args = parser.parse_args()

    dataset_arg = args.dataset_flag or args.dataset
    target_path = default_inventory_path(dataset_arg)

    print(f"Loading blocks from {target_path}...")
    blocks = load_dataset_from_jsonl(target_path)
    print(f"Auditing {len(blocks)} blocks...")
    summary = run_zero_corruption_audit(blocks, show_progress=not args.quiet)
    print_audit_report(summary)

    if summary.anomalies:
        raise RuntimeError(
            f"True table corruption detected: {len(summary.anomalies)} blocks unwrapped unexpectedly."
        )
    print("[SUCCESS] True table corruption: 0.00%. All true tables preserved.")
    return 0


if __name__ == "__main__":
    main()
