# `edgar_sec/domain/forms/common/` — Form-Agnostic Contracts, Schemas, and Aliases

## Purpose

Shared domain contracts for form aliases, checkmark tokens, cover phrase rules,
declarative checkbox schemas, and cover-label vocabularies. These leaf contracts
support normalization without owning runtime evaluator dispatch.

## Contracts

- **Alias resolution**: `resolve_alias()` is the only entry point to resolve raw form strings to families; `form_family()` only collapses suffixes.
- **Suffix collapse**: Removes each suffix at most once in fixed priority order.
- **Declarative constraints**: Statutory cover requirements are `CheckboxConstraint` values in `STATUTORY_CHECKBOX_CONSTRAINTS`.
- **One mark vocabulary**: `mark_token_state()` is the only token-to-state reader; a bare mark needs an explicit contextual opt-in, and an underscore-only run is unfilled data rather than a mark.
- **Zero I/O**: Zero internal dependencies on `infra`, `engine`, `pipelines`, or `apps`.

## Deliberate gaps

- **Alias vocabulary covers only periodic and current report families**: Registration, proxy, ownership, and beneficial-ownership forms have no alias entries; callers must decide their families.
