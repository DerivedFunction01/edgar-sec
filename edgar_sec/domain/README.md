# `edgar_sec/domain/` — Layer 1: value objects, vocabulary, and schema contracts

Layer 1 holds the facts every other layer agrees on and none of them may
specialise: identity primitives, EDGAR URL shapes, statutory vocabulary, Arrow
schemas, and the frozen dataclasses that cross layer boundaries. It performs no
IO, opens no files, and reaches no network.

## Purpose

`edgar_sec/domain/` is the only place a value may be *defined* rather than
*produced*. A CIK, a form family, a cover-page label, a dataset column list: all
of it is declared here once, and `infra`, `engine`, and `pipelines` import
downward. What this layer is not: it does not fetch, persist, parse, classify, or
schedule. A rule that needs a request, a file handle, a thread, or a stage
counter belongs above this layer.

## Contracts

- **Immutability**: Values are defined once with single owning modules; consumers read them rather than restating them.
- **Zero I/O**: Vocabulary tables are immutable; domain modules perform no filesystem, network, or database I/O.
- **Deterministic keys**: Document locator and occurrence keys have one canonical derivation; spellings are pinned by cross-layer tests.
- **Schema stability**: Compiled alternations use `foundation.regex.builder` (longest-first ordering); schema version constants are bumped when columns change.

## Deliberate gaps

- **A few registered surfaces have no domain builder**: the ticker files and the CIK lookup file are governed surfaces in the rule table, but their fetch URLs live as literals in the cohort pipeline's source catalog; every other fetched SEC shape is built in this layer.
- **The `layer-boundary` scanner does not check for cycles**: It flags only upward layer-rank dependencies; same-layer import cycles remain a review responsibility.
