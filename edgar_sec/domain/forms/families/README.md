# `edgar_sec/domain/forms/families/` — Form-Family Evidence Packs and Item Taxonomies

## Purpose

Partitions form-specific evidence and structural definitions across the three SEC filing
families: `annual/` for Form 10-K and 20-F, `quarterly/` for Form 10-Q, and `current/`
for Form 8-K. Each subpackage supplies body-start evidence, Part/Item structural
taxonomies, and — for annual and quarterly — its checkbox schema.

## Contracts

- **Per-family data is isolated; the derivation builder is not.**
  `build_taxonomy_derived(items, parts)` splits items into early and late, builds the
  late-item pattern, and compiles a lexical matcher over normalized tokens, so
  structural item detection is a single pass rather than a scan per keyword. It is
  owned by `annual/taxonomy.py` and called by all three families at import — the one
  cross-family dependency — while the evidence packs and item tables stay per-family,
  so changing one family's terms or headings cannot alter another's.
- **Each family publishes a body-lexical pack** built from its own term constants and
  attached as the family's body evidence. This is important: the cover engine
  compiles whatever pack the evidence carries, and the cover boundary's
  `BODY_PROSE_FALLBACK` signal scores body-root candidates against it. Without an
  explicit pack the fallback derives its tiers from flat vocabulary instead, which
  changes body detection on real filings.
- **Two annual tier policies deviate deliberately.** `body_forward` matches
  lowercased while the other annual tiers fold case, and `body_phrase_soft` is a
  supporting tier while the others are not, so a soft match scores without asserting
  a body root. The tier table itself lives in `annual/evidence.py`.
- **Tier overlap is preserved, not tidied.** Some annual terms are claimed by more than
  one tier, so a single occurrence can satisfy two tiers and inflate a score.

## Deliberate gaps

- **No 6-K taxonomy.** `resolve_alias("6-K")` returns `"6-K"` and `current/` covers
  8-K, but no subpackage declares a 6-K item taxonomy or 6-K-specific terms, so a 6-K
  filing has no structural definitions to match and falls back to the shared
  current-report evidence.
- **`FORM_8K_DERIVED` has no parts.** `current/taxonomy.py` declares an empty Part
  structure, so the derived lookup's `late_parts` is empty and only item-level
  detection applies to an 8-K.
