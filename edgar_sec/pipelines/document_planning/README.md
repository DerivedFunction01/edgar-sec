# `document_planning`

## Purpose

Planning turns a published filing-catalog plan and an optional pinned inventory snapshot
into an immutable accession-document target plan for later acquisition.

## Contracts

- Planning performs no network access and never mutates catalog or inventory state.
- A filing-catalog plan must use schema 1.4 and declare target-part byte sizes and
  SHA-256 digests. Older plans lack the current target feature shape and are refused;
  republish them from the rebuilt filing catalog.
- Inventory-backed plans pin one immutable snapshot ID and verify its lineage and
  relation parts. `current` is resolved once; catalog-only plans require a profile
  whose requests are primary-only.
- Catalog and inventory filing facts must agree. Inventory-backed planning has no
  catalog-locator fallback; an accession absent from the snapshot is recorded as
  `unresolved / accession_not_indexed`.
- Published manifests pin both sources, profile and matcher versions, coverage,
  status totals, and every output part. Reuse requires byte-identical plan content.
- New bundle version 2 identities include the bundle schema and matcher versions,
  and each target part declares and verifies its byte size. Discovery accepts only
  bundle version 2 with matcher v2.
- Bundle-sequence and constructed-package rows are candidates, not proof that the
  requested document exists. Planning never starts acquisition.
- **Current locator selection**: A usable matched child link selects `direct_url`
  for ordinary paths; exact placeholder-primary filenames override direct retrieval.
  The exact names are `0000.txt`, `0000.htm`, `0001.txt`, and `0001.htm`, independent
  of form/date; nested paths and arbitrary suffix matches are excluded. Planning selects
  `bundle_sequence` only when inventory supplies the exact observed primary filename,
  a positive sequence, and the pinned accession bundle URL. In catalog-only mode a
  `0001.*` placeholder primary instead constructs its accession-numbered direct link
  (`<accession>-0001.<ext>`) and is matched as `direct_url`; a `0000.*` primary is
  ignored (sequence 0 does not exist) and treated as no primary evidence.
  A catalog-only primary target with no usable primary falls back to the constructed
  complete-submission bundle URL, split by the accession's filing year (from
  `filing_date`): filed in 2000 or later, it publishes a constructed `bundle_sequence`
  at sequence 1 only under the `exact_form_with_lazy_index` selection with a
  lazy-index form family, leaving verification to acquisition's screen-and-recover;
  filed before 2000, it publishes `bundle_scan` regardless of selection, and
  acquisition selects the document inside the bundle by SGML type, since the filing
  index carries no further selection evidence for that era. A missing or unparseable
  filing year keeps the target unresolved. Filing-catalog URL
  construction may accession-qualify a placeholder child href; this locator
  construction does not authorize retrieval. Secondary
  links continue to use their observed index hrefs without rewriting.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `compare` | compare immutable target plans or profile rules | `[--base-plan-id]`, `[--new-plan-id]`, `[--base-profile-id]`, `[--new-profile-id]`, `[--output]`, `[--output-id]`, `[--artifacts]`, `[--json]` |
| `inspect` | validate and inspect a plan | `--plan-id`, `[--artifacts]`, `[--json]` |
| `plan` | publish a deterministic target plan | `--catalog-plan`, `[--inventory]`, `[--profile-id]`, `[--auto-primary-profile]`, `[--artifacts]`, `[--json]` |
| `status` | list profiles and published plans | `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# List profiles and published plans
python run.py planning status

# Publish a deterministic plan
python run.py planning plan --catalog-plan plan-2024-01-15 --profile-id primary-docs --inventory

# Inspect a published plan
python run.py planning inspect --plan-id plan-2024-01-15

# Compare two published target plans
python run.py planning compare --base-plan-id plan-before --new-plan-id plan-after
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
└── document_planning/
    ├── plans/
    │   └── {plan_id}/
    │       └── plan.json
    ├── profiles/
    │   └── {profile_id}.json
    └── review-runs/
```
<!-- AUTOGEN:PATHS:END -->

## Deliberate gaps

- `exact_form` is dropped as a catalog-direct policy. The policy axis collapsed to
  two choices: `submitted_primary` (fast, zero extra requests) and
  `exact_form_with_lazy_index` (verifies the fetched primary; on a confirmed type
  mismatch, fetches `-index.html` only to recover the true form and never again for
  transport failures or missing evidence). The failed-closed `exact_form` mode became
  an awkward middle ground: non-report forms have no inversion risk, and for report
  forms a failure that refuses the exhibit with the index still in reach produced
  worse outcomes than either extreme.
- The baseline profile is generated from the operator or CLI, not inferred from
  inventory observations; users may edit or create additional profiles.
- No source refresh, inventory projection, or acquisition is performed. Operators
  use `inventory project` separately when coverage is missing, then plan from its
  published snapshot.
- Constructed XBRL package URLs are unverified candidates; availability is not
  probed during offline planning.
- Advertised child size, full-submission bundle size, and catalog-reported catalog size
  are distinct observations. They are not compared to select direct versus bundle
  retrieval; a size-aware optimizer is deferred. The exact-filename placeholder rule is separate
  and requires an advertised bundle URL plus exact observed positive sequence; it does
  not apply to the complete-submission accession `.txt` filename.
- Constructing an XBRL ZIP candidate does not authorize fetching or unzipping it.
  catalog availability evidence and a separate policy are required before execution or
  asset selection.
