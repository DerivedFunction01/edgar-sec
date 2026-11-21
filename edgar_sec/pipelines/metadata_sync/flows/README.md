# `edgar_sec.pipelines.metadata_sync.flows` — Composed Legs and Entry Points

The composed legs of the pipeline — augmentation, refresh, and daily-index
reconciliation — plus the operator surface, the CLI entry point, and the
smoke test.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Snapshot augmentation machinery | [augmentation.py](augmentation.py) |
| Augmentation command flow | [augment_flow.py](augment_flow.py) |
| Current-filings refresh leg | [refresh.py](refresh.py) |
| Daily-index reconciliation leg | [reconcile.py](reconcile.py) |
| Operator surface | [operator.py](operator.py) |
| CLI entry point | [cli.py](cli.py) |
| Smoke test | [smoke_test.py](smoke_test.py) |

## Contracts

- Augmentation computes `requested - base` with shared cohort operations
  and writes its verified delta under metadata transient storage.
- The daily index is a discovery trigger, never a metadata source:
  `reconcile` publishes exactly the accessions the index proves the branch
  tip lacks, and a zero-diff range publishes nothing.
- Unhandled domain exceptions bubble up from the command handlers to
  `cli.py` for uniform exit handling.

## Deliberate Gaps

- Subcommand handlers live in `commands/`; this group is the machinery and
  entry points beneath them.
