# `edgar_sec/engine/company_family` — company-family assignment

Assigns every registrant a family key so downstream selection does not over-represent one
registrant group. Assignment is a DuckDB pipeline over the compiled registrant universe;
the result is published as a Parquet relation, not an in-memory index.

## Purpose

Produce one deterministic `company_family` key per CIK. The key is namespaced so a
sponsor's securitised vehicles and the sponsor's own operating entity are separate families
by construction rather than by coincidence of spelling.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `tokens.py` | Name normalization, identity stems, SPV marking, umbrella-phrase parsing. |
| `assignment.py` | Universe-scale assignment as relations; the published column set. |

## Contracts

- **Every registrant gets exactly one family key.** A name yielding no identity is keyed
  `cik:<cik>`, so unidentifiable registrants never share a bucket.
- **Keys are namespaced.** `entity:` for non-vehicle names, `spv:` for securitised ones,
  `cik:` for names with no identity. The prefix is what keeps a sponsor and its own SPVs
  apart.
- **All of one sponsor's SPVs form one family**, across instrument and product lines. A
  parent entity stays outside that family unless its own name carries an SPV marker.
- **Only `SPV_MARKERS` classifies.** `SPONSOR_BOUNDARY_WORDS` is broader and only locates
  where a sponsor name ends inside a longer title.
- **Assignment is deterministic.** It depends on the roster and the word lists, not on
  input ordering or process state. The cache id covers both.
- **Nothing is fetched.** The roster is the only input; the engine has no source to reach.

## Command surface

None. Library package, no CLI.

## Public surface

- `build_assignment(con, roster_source)` returning `FamilyAssignmentStats`, and
  `assignment_relation_sql(path)` for a downstream join — `assignment.py`.
- Normalization helpers: `identity_tokens`, `normalized_key`, `has_spv_marker`,
  `sponsor_candidate`, `umbrella_parent`, `apply_aliases` — `tokens.py`.

A caller that wants a cached, reusable artifact should use
`edgar_sec.pipelines.metadata_sync.family_index.ensure_family_index`, which owns the
content-addressed path, the manifest, and the reuse check.

## Mirrored tests

Mirrored coverage lives under `tests/engine/company_family/`.

## Deliberate gaps

- **No representative or cluster-member surface.** Selection needs only
  `(cik, company_family)`; nothing exposes a parent/variant distinction or a cluster
  membership list.
- **No fuzzy matching or external entity graph.** A registrant with no name relationship
  to a known parent keeps its own family.
- **An unresolvable sponsor falls back to the name's own stem.** A one-token sponsor with
  no matching entity in the corpus stays its own group rather than merging across
  sponsors, so a sponsor named only in its vehicles may form several families.
- **Sponsor resolution is prefix-based and single-valued.** Where two sponsors share a
  leading name, the longer corpus-known prefix wins.
