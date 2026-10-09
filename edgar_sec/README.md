# `edgar_sec`

This file maps the package layers and their ownership boundaries. Each package
README documents its own contracts and public surface.

## Layers

Imports flow **downward only**. A layer may import from the layers beneath it
and never from the layers above. This is not a convention — the
`layer-boundary` policy scanner parses every import in the package and fails the
gate on a violation.

```text
Layer 5  apps/          read-only, operator-facing consumers of published artifacts
           │            may read every layer below; nothing may import it
Layer 4  pipelines/    orchestration: CLI, operator, planner, worker, merger
           │            the only layer permitted to sequence the others
Layer 3  engine/       filing transformations and feature construction
           │
Layer 2  infra/        I/O adapters: SEC HTTP, broker, DuckDB, Parquet, CAS
           │
Layer 1  domain/       data contracts and vocabularies. No IO.
           │
Layer 0  foundation/   runtime, memory, hashing, compression, settings, scanners
                         zero internal dependencies on upper layers
```

### Layer roots

Each layer owns one or more packages. Read the layer root README for contracts; read the package READMEs for details.

- **foundation/** (Layer 0): runtime, memory, hashing, compression, settings, scanners
- **domain/** (Layer 1): data contracts and vocabularies. No IO.
- **infra/** (Layer 2): I/O adapters: SEC HTTP, broker, DuckDB, Parquet, CAS
- **engine/** (Layer 3): filing transformations and feature construction
- **pipelines/** (Layer 4): orchestration: CLI, operator, planner, worker, merger
- **apps/** (Layer 5): read-only, operator-facing consumers of published artifacts |

## Shared engineering contract

Layer boundaries, import/export rules, resource limits, settings, and the mirrored
test-tree contract are defined normatively in [`AGENTS.md`](../AGENTS.md).

## Deliberate gaps

This root package is an architecture map rather than an execution layer; its
capability gaps belong to the owning layer or package README.
