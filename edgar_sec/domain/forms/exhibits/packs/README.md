# exhibit.packs

Declarative exhibit pack definitions for SEC Item 601 and Form 20-F classification.

## Purpose

This package hosts frozen data contracts (`ExhibitPack`) that describe exhibit evidence
in tiered, form-generic terms. Each pack exports anchors, secondary tokens, and veto
signals as plain string tuples. The engine compiles these into regex patterns at runtime
with `foundation.regex.builder.build_alternation`.

## Contracts

- **Declarative only**: Packs contain string metadata; zero regex compilation or I/O.
- **Form-agnostic**: Anchors and tokens never hardcode `"Form 10-K"` unless form-exclusive.
- **Tiered**: Each pack declares `tier="tier1"` / `"tier2"` / `"tier3"` for sparse prefiltering.
- **Immutable**: All `ExhibitPack` instances use `@dataclass(frozen=True, slots=True)`.

## Deliberate gaps

- **No registry wiring**: Pack resolution and sub-pack disambiguation live in `registry.py`.
- **No compiled patterns**: Regex compilation happens in `engine/forms/plugins/exhibit_selection.py`.
