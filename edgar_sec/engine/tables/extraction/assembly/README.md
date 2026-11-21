# assembly

## Purpose

Filing-level assembly: `context_production` produces every table context;
`filing_passes` and `finishing` run the filing-level passes; `assembly`
groups a filing's classified tables into logical statements and arbitrates
their relations.

## Contracts

- **Contexts are produced once, by one function**: `context_production.
  produce_contexts` is the only context-production path — corpus builder,
  pipeline, and facade fast path all call it and none assembles a context of
  its own.
- **Filing-level facts are computed once** in document normalization and
  carried on the context: the TOC span, the closing span, the region map,
  the exhibit inventory, and the per-document geometry set.
- **Assembly is relational arbitration over measured relations**: split
  fragments join on continuity signals and row bounds bind the assembled
  group; each family holds one main slot per filing, ranked, with further
  groups kept as variants; every arbitration act records its provenance.

## Deliberate gaps

- **No classification lives here**: assembly consumes the cascade's claims;
  it names no family itself.
