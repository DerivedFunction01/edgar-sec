# `edgar_sec/domain/forms/common/` — Form-Agnostic Contracts, Schemas, and Aliases

## Purpose

Shared domain contracts for form aliases, checkmark tokens, source phrase rules,
declarative checkbox schemas, and cover-label vocabularies. These leaf contracts
support normalization without owning runtime evaluator dispatch.

## Contracts

- **Alias resolution**: `resolve_alias()` is the only entry point to resolve raw form strings to families; `form_family()` only collapses suffixes.
- **Suffix collapse**: Removes each suffix at most once in fixed priority order.
- **Declarative constraints**: Statutory cover requirements are `CheckboxConstraint` values in `STATUTORY_CHECKBOX_CONSTRAINTS`.
- **One mark vocabulary**: `mark_token_state()` is the only token-to-state reader; a bare mark needs an explicit contextual opt-in, and an underscore-only run is unfilled data rather than a mark.
- **Phrase policy is declarative**: `PhraseRule` records category, family/section scope, and extraction effect without matching or mutating source text.
- **Missing markers are policy-scoped**: Common token classification does not make a marker missing outside an explicit field policy.
- **Zero I/O**: Zero internal dependencies on `infra`, `engine`, `pipelines`, or `apps`.

## Deliberate gaps

- **Alias vocabulary is wider than the profile catalog**: `FORM_FAMILY_ALIASES` covers families beyond those with a processing profile, including registration, proxy, ownership, and beneficial-ownership forms; a resolved family may still have no processing profile, and callers must handle that case. The alias table in `aliases.py` is authoritative for the families covered.
