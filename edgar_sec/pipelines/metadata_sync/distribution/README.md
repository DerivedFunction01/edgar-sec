# `edgar_sec.pipelines.metadata_sync.distribution` — Distribution and Merge

Chunk-to-worker assignment, the distributed worker bundle lifecycle, and
snapshot merge/publication.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Chunk-to-worker assignment | [assignment.py](assignment.py) |
| Worker bundle lifecycle | [distribution.py](distribution.py) |
| Distribution over the execution machinery | [distribution_adapter.py](distribution_adapter.py) |
| Snapshot merge and publication | [merger.py](merger.py) |

## Contracts

- Merge publishes durable snapshots to the selected DAG branch under a
  shared CAS guard; `--expected-branch-tip` pins the expected branch
  pointer and refuses the publish if the branch moved.
- Assignment datasets land in the plan bundle's `assignments/` directory,
  one mapping per distribution.

## Deliberate Gaps

- Augmentation is single-host: its derived delta is executed and merged
  within the command rather than exported for distributed workers.
