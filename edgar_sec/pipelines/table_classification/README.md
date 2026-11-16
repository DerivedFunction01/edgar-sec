# table_classification

Layer 4 pipeline that runs the free-text table classifier in production:
runs are planned against the family-profile registry over the
document-acquisition snapshot tip, each filing is classified through the
engine's one context production and cascade, and the run's outputs are
assembled for publication as a Parquet DAG store. The store publishes
the merged run over the source snapshot tip under one provenance
header, and the facade's pipeline version of `classified_tables` reads
the published store tip read-only.

## Contracts

- **Plan against the registry**: every run is planned first. The plan
  serializes as versioned relations (schemas.py, PLAN_FORMAT_VERSION):
  a provenance header (registry state, source snapshot id,
  normalize/renderer versions), filing rows, profile application,
  document targets in document_planning's role/type/optional shape with
  per-target geometry expectations, and work items. A registry change
  plans a new run; it never re-scopes an old one.
- **Generic planning**: the planner consumes generic rows the CLI
  translator emits from the registry and never imports the registry;
  planning and acquisition learn nothing about the classifier. The
  header's registry_state is the sha256 fingerprint over the canonical
  serialization of the registry (PROFILES);
  the planner carries it opaquely, so the store's provenance and both
  facade paths' stamps stay comparable under D2. The carried value is
  the translator's registry_state() string, "sha256:<hex>": sha256 over
  json.dumps of the payload {"profiles"} — the asdict
  serializations of PROFILES — with sorted
  keys and compact separators; the bare hex appears only inside facade
  stamp strings.
- **Outputs, never plan content**: filing-level facts, contexts, and
  classification results are run outputs. The worker stages them per
  work item; the merger validates completeness, key uniqueness, and
  count reconciliation before assembling the merged relations the
  store publishes.
- **Derived, never a source**: the store is rebuildable from the
  source snapshot plus a run's merged outputs; nothing hand-edits it,
  and republishing identical content is a no-op at the same tip.
- **One checkpoint per run**: each store publish is a single DAG
  checkpoint node carrying the plan relations and the merged output
  relations verbatim, plus the store's `run_provenance` header —
  content-addressed from the source snapshot id, the registry state,
  the plan, and the relation digests; publication is CAS-guarded
  against the branch tip it read, and merged digests are verified
  against `run_manifest.json` before publishing.
- **Two relations are store-derived**: `evidence` decomposes each
  classification's evidence JSON into one row per point, and
  `assembled_tables` projects the classifications assembly claimed
  (family, assembled family, mechanism) — both derived at publish
  time from the verified merged output, never separate inputs.
- **Provenance travels with reads**: the store records the source
  snapshot id, plan and run-output versions, registry state, and the
  normalize/renderer versions; reads carry the store snapshot id and
  the source snapshot id so a stale store never answers as current.
- **Reads are read-only**: the store reader resolves the tip through
  the DAG catalog, writes nothing, and answers honest absence — no
  store or no filing is `None`, never a live recomputation.
- **Compute once**: the worker calls the engine's context production
  and exhibit resolver; it derives no filing-level fact of its own and
  owns no resolver. Two entries share that one flow:
  classify_documents classifies from acquired payloads (normalize,
  exhibit resolution, production); the products-side entry
  classify_products classifies from produced DocumentInputs and never
  re-normalizes — fixture and review callers holding stored
  normalization products enter there.
- **Corpus boundary**: only acquired holdings are classified; a filing
  absent from the snapshot tip is a filing record with an honest
  absence reason, never a live classification.

## Deliberate gaps

- **No acquisition**: the pipeline consumes the document-acquisition
  snapshot read-only; declaring and acquiring exhibit targets belongs
  to planning and acquisition.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
.venv/bin/python -m edgar_sec.pipelines.table_classification.cli status
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
<!-- AUTOGEN:PATHS:END -->
