# `edgar_sec/domain/forms/families/` — Form-Family Evidence Packs and Item Taxonomies

## Purpose

Partitions form-specific evidence and structural definitions across SEC filing
families: `annual/` for Form 10-K and 20-F, `quarterly/` for Form 10-Q, `current/`
for Form 8-K, `ownership/` for Section 16 insider reports (Form 4), `registration/`
for Securities Act registration statements (Form S-1), and `beneficial_ownership/` for Schedule 13D and Schedule 13G.
Each subpackage supplies
declarative processing profiles, body evidence, and structural taxonomies.

## Contracts

- **Per-family data isolation**: Evidence packs and item tables are isolated per family; `build_taxonomy_derived()` is the only cross-family dependency.
- **Body-lexical packs**: Each family publishes a body-lexical pack built from its own term constants.
- **Tier policies**: `body_forward` matches lowercased; `body_phrase_soft` is a supporting tier.

## Deliberate gaps

- **No 6-K taxonomy**: `current/` covers 8-K but declares no 6-K item taxonomy or terms.
- **`FORM_8K_DERIVED` has no parts**: Only item-level detection applies to an 8-K.
