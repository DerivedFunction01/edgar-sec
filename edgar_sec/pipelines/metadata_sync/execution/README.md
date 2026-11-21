# `edgar_sec.pipelines.metadata_sync.execution` — Fetch and Checkpoint Machinery

Per-CIK fetch and normalize work: the chunk worker, chunk checkpoints,
completed-chunk discovery, and snapshot reading helpers.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Per-CIK fetch and normalize worker | [worker.py](worker.py) |
| Chunk checkpoint write and validation | [checkpoints.py](checkpoints.py) |
| Completed-chunk discovery | [discovery.py](discovery.py) |
| Published snapshot reading | [snapshot.py](snapshot.py) |

## Contracts

- A run guarantees one row per requested CIK, including failures.
- Checkpoint validation and chunk coverage are owned by this group.

## Deliberate Gaps

- No planning (owned by `core`) and no merge or publication (owned by
  `distribution`).
