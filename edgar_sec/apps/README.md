# `edgar_sec/apps` — Layer 5: operator applications and client workflows

An app is an operator-facing consumer of the repository's data and capabilities.
It houses the inspection viewer (`apps.viewer`) for browsing published artifacts,
and the high-throughput pipeline runner (`apps.runner` / `apps.client`) that
coordinates pipeline primitives into unified, ergonomic workflows.

`apps/` sits at rank 5, above `pipelines/` (4). It may import anything beneath it.
The rule enforced by the `layer-boundary` scanner is downward-only: nothing below
`apps/` may import from `apps/`.

## Contracts

- **Downward-only imports**: Apps may import from pipelines, engine, infra, domain, and foundation. Nothing below apps may import from this layer.
- **Pipeline delegation**: Runners coordinate verified pipeline primitives without duplicating storage, CAS, or worker scheduling.
- **In-memory analytical binding**: DuckDB sessions bound by apps remain in-memory and read published Parquet/CAS artifacts directly.
- **Loopback binding**: Web interfaces bind strictly to loopback by default with no external multi-user exposure.

## Deliberate gaps

- **No custom ETL pipeline logic**: Batch execution logic belongs in `pipelines/`; apps only orchestrate existing coordinators.
- **No remote multi-user authentication**: Apps provide local operator tooling and developer workflows without a shared authentication layer.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
python run.py viewer --help
python run.py fetch --help
```

