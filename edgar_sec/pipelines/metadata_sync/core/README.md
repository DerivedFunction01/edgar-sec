# `edgar_sec.pipelines.metadata_sync.core` — Shared Base

The shared base of the metadata sync pipeline: cohort roster identity,
plan construction, run options and specs, the SEC
submissions client, progress events, the run lock, and validation helpers.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Cohort roster identity and schema | [roster.py](roster.py) |
| Deterministic plan construction | [planner.py](planner.py) |
| Run option and spec shapes | [options.py](options.py), [specs.py](specs.py) |
| SEC submissions HTTP client | [sec_client.py](sec_client.py) |
| Progress events, run lock, validation | [progress.py](progress.py), [run_lock.py](run_lock.py), [validation.py](validation.py) |

## Contracts

- Every other `metadata_sync` group imports this group; this group imports
  no sibling group.
- Metadata planning is offline and never refreshes official sources.
- The shared CIK-set identity and the metadata roster identity are separate
  contracts.

## Deliberate Gaps

- No execution, distribution, or publication logic lives here; those are
  owned by `execution`, `distribution`, and `flows`.
