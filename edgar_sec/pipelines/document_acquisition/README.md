# document_acquisition

Layer 4 pipeline contract foundation for S9 accession-document acquisition.

## Purpose

This package projects versioned S6 target plans into bounded S9 work orders and owns the run-state and fixture-store foundations. Transport, body selection, processing, review artifacts, and snapshot publication remain separate stages.

The launcher, CLI, and operator surfaces are registered. The offline `project` track is implemented; acquisition, processing, fixture orchestration, review, and snapshot tracks return explicit not-implemented or gate-blocked results.

## Contracts

- **Pinned selection policy**: Catalog-direct selection is exactly `submitted_primary` or `exact_form_with_lazy_index`; S9 cannot replace or upgrade it.
- **Distinct evidence**: Processing role, requested type, expected statutory type, index designation, physical sequence, and observed body type remain separate facts.
- **Transient ownership**: Acquisition runs and staged bodies belong under the shared transient root until snapshot publication or explicit discard.
- **Payload boundary**: Future snapshot payloads use separate binary and text Parquet relations; this package does not introduce an external CAS or durable payload directory.

## Deliberate gaps

- **No network runner**: Bounded HTTP streaming, exact-sequence extraction, acquisition attempts, fixture orchestration, and workers remain unimplemented.
- **No processing or publication**: S10 processing and S11 Parquet/DAG publication remain absent; S11 requires representative S9/S10 evidence and explicit approval.
- **No S7d review builder**: Selected S9 bodies and S10 processor outputs/fingerprints do not exist yet, so review build/compare remain placeholders rather than fabricated reports.
- **No snapshot reader**: Acquisition snapshot relations and a published acquisition DAG do not exist; status/audit are gate-aware placeholders, not queries against S5/S6 or legacy storage.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `fixture` | manage S9 response fixtures | — |
| `process` | process acquired target bodies | `--run-id`, `[--workers]`, `[--artifacts]`, `[--json]` |
| `project` | project a published S6 target plan | `--plan-id`, `[--artifacts]`, `[--json]` |
| `publish` | publish an approved S11 snapshot | `--run-id`, `[--branch]`, `[--expected-branch-tip]`, `[--artifacts]`, `[--json]` |
| `review` | build and compare review artifacts | — |
| `run` | acquire pending S9 target bodies | `--run-id`, `[--retry-failures]`, `[--workers]`, `[--confirm-stale-lock]`, `[--artifacts]`, `[--json]` |
| `snapshot` | inspect S11 status and evidence | — |
| `status` | inspect resumable acquisition runs | `[--run-id]`, `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
python run.py acquisition --help

# Placeholder tracks return stable machine-readable not-implemented status.
python run.py acquisition project --plan-id dplan-example --json
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── document_acquisition/
│   ├── fixtures/
│   │   └── {fixture_id}/
│   │       ├── fixture.sqlite
│   │       └── manifest.json
│   ├── review-runs/
│   └── snapshots/
│       └── {snapshot_id}/
├── document_planning/
│   └── plans/
│       └── {plan_id}/
├── runtime/
└── transient/
    └── document_acquisition/
        └── {run_id}/
            ├── staging/
            ├── work_order/
            ├── cancelled.json
            ├── run.lock
            ├── run_manifest.json
            └── state.sqlite
```
<!-- AUTOGEN:PATHS:END -->

The registered TODO commands create no run, fixture, review, or snapshot artifacts.
