# `edgar_sec/domain/forms/families/` — Form-Family Evidence Packs and Item Taxonomies

## Purpose

Partitions form-specific evidence and structural definitions across SEC filing
families: `annual/` for Form 10-K and 20-F, `quarterly/` for Form 10-Q, `current/`
for Form 8-K and 6-K, `ownership/` for Section 16 insider reports (Forms 3, 4, and
5), `registration/` for Securities Act registration statements (Forms S-1, S-3,
S-4, and S-8), `beneficial_ownership/` for Schedule 13D and Schedule 13G,
`form144/` for Form 144, and one `form_*/` package per remaining modelled form.
Each subpackage supplies
declarative processing profiles, body evidence, and structural taxonomies.

## Contracts

- **Per-family data isolation**: Evidence packs and item tables are isolated per family; `build_taxonomy_derived()` is the only cross-family dependency.
- **Body-lexical packs**: The annual, quarterly, current, and registration families publish a body-lexical pack built from their own term constants; most `form_*/` families publish no body-lexical pack.
- **Tier policies**: `body_forward` matches lowercased; `body_phrase_soft` is a supporting tier.

## Deliberate gaps

- **The 6-K taxonomy holds one validated item**: `current/` declares the 6-K item table beside the 8-K table, and the 6-K profile is its own; only the press-release item cleared the adoption bar, so the other drafted structures (financial statements, governance notice, dividend / capital return, results announcement) are not modelled as items, and 6-K content beyond the press release rides the current-report evidence unnamed.
- **`FORM_8K_DERIVED` has no parts**: Only item-level detection applies to an 8-K.
