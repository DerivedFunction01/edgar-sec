# `edgar_sec/domain/forms/families/` — Form-Family Evidence Packs and Item Taxonomies

## Purpose

Partitions form-specific evidence and structural definitions across the three SEC filing
families: `annual/` for Form 10-K and 20-F, `quarterly/` for Form 10-Q, and `current/`
for Form 8-K. Each subpackage supplies body-start evidence, Part/Item structural
taxonomies, and — for annual and quarterly — its checkbox schema.

## Contracts

- **Per-family data isolation**: Evidence packs and item tables are isolated per family; `build_taxonomy_derived()` is the only cross-family dependency.
- **Body-lexical packs**: Each family publishes a body-lexical pack built from its own term constants.
- **Tier policies**: `body_forward` matches lowercased; `body_phrase_soft` is a supporting tier.

## Deliberate gaps

- **No 6-K taxonomy**: `current/` covers 8-K but declares no 6-K item taxonomy or terms.
- **`FORM_8K_DERIVED` has no parts**: Only item-level detection applies to an 8-K.
