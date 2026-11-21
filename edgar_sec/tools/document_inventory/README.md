# document_inventory

## Purpose

The offline scale check for the document-inventory progress journal.
`progress_scale_check` fabricates a synthetic inventory work order — up to
236,000 `InventoryEntry` / `IndexWorkItem` rows with synthetic parent, cohort,
and source identities — and runs it through the pipeline's real checkpoint,
progress-journal, and run-manifest machinery to prove the journal holds at
scale. It is a measurement driver, not a pipeline stage, so it lives in tools;
the document-inventory pipeline runs without it.

## Contracts

- **Opt-in only**: the simulation runs only under `--run-simulation`; without
  the flag the CLI exits before writing anything.
- **Scratch-only writes**: every write lands under the caller-supplied
  `--scratch` directory, which must be new or empty and separate from the
  configured artifacts root; no snapshot is ever published.
- **Offline**: the check performs no network access and records
  `network_access: none` in its result.
- **Downward imports only**: as layer 6 it imports the pipeline's internals by
  absolute `edgar_sec.pipelines.document_inventory` paths; no lower layer
  imports this package.

## Deliberate gaps

- **Synthetic population only**: rows are fabricated, so the check proves
  scale and recovery behaviour of the journal, never real-catalog
  correctness.
- **No pipeline wiring**: nothing in `edgar_sec.pipelines` imports or invokes
  this package; it is run directly as
  `python3 -m edgar_sec.tools.document_inventory.progress_scale_check`.
