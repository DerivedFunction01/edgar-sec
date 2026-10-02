# `edgar_sec/domain/forms/families/` — Form-Family Evidence Packs and Item Taxonomies

## Purpose

Partitions form-specific evidence and structural definitions across the three SEC filing
families:

1. `annual/` — Form 10-K and 20-F (annual and foreign private issuer reports)
2. `quarterly/` — Form 10-Q
3. `current/` — Form 8-K and 6-K (current reports and foreign private issuer updates)

Each subpackage supplies body-start evidence, Part/Item structural taxonomies, and — for
annual and quarterly — its checkbox schema.

## Layout

| Subpackage / Module | Responsibility |
| :--- | :--- |
| `annual/evidence.py` | Body-phrase, strong, header, general, weak, forward, and verb term sets; public-float and share-count phrases; 25 cover-exclusion terms; `ANNUAL_BODY_LEXICAL_PACK`, `AnnualReportEvidence` |
| `annual/taxonomy.py` | `PARTS`, `ITEMS`, `FORM_10K_ITEMS`, `FORM_20F_ITEMS`, their `_DERIVED` forms, `build_taxonomy_derived()` |
| `annual/checkmarks.py` | `ANNUAL_CHECKBOX_SCHEMA` |
| `quarterly/evidence.py` | `QUARTERLY_BODY_STRONG_TERMS`, `QUARTERLY_BODY_WEAK_TERMS`, `QUARTERLY_BODY_LEXICAL_PACK`, `QuarterlyReportEvidence` |
| `quarterly/taxonomy.py` | `PARTS`, `ITEMS`, `FORM_10Q_ITEMS`, `FORM_10Q_DERIVED` |
| `quarterly/checkmarks.py` | `QUARTERLY_CHECKBOX_SCHEMA` |
| `current/evidence.py` | Body phrase, strong, and weak term sets; `CURRENT_BODY_LEXICAL_PACK`, `CurrentReportEvidence` |
| `current/taxonomy.py` | `PARTS` (empty), `ITEMS`, `FORM_8K_ITEMS`, `FORM_8K_DERIVED` |

## Contracts

- **Symmetric family isolation:** the three subpackages share no module. Changing an Item
  heading in `annual` cannot alter `quarterly` or `current`. The one shared
  dependency is downward: all three import `domain/forms/common/`.
- **Compiled taxonomy derivations.** `build_taxonomy_derived(items, parts)` splits items
  into early/late, builds a `late_item_re`, and compiles a lexical matcher over normalised
  tokens, so structural item detection is a single pass rather than a scan per keyword.
  Each family calls it once at import; only `annual/` exposes the builder.
- **Each family publishes a body-lexical pack.** `ANNUAL_BODY_LEXICAL_PACK` (8 tiers),
  `QUARTERLY_BODY_LEXICAL_PACK` (4), and `CURRENT_BODY_LEXICAL_PACK` (4) are built
  from that family's own term constants and attached as the family's
  `body_lexical` field. This is load-bearing: `engine/forms/cover/rules.py::_lexical_for`
  compiles whatever pack is attached, and the cover boundary's `BODY_PROSE_FALLBACK` signal
  scores body-root candidates against it. Without an explicit pack the fallback derives at
  most 3 tiers from flat vocabulary, which changes body detection on real filings.
- **Two annual tier policies are deliberate and pinned by tests.** The `body_forward` tier
  is `CaseMode.LOWERCASE` while every other annual tier is `CaseMode.FOLD`; `body_phrase_soft`
  carries `support=True` while every other tier carries `False`, so a soft match scores
  without asserting a body root.
- **Tier overlap is preserved, not tidied.** Three annual terms (`approximately`,
  `operations`, `overview`) are claimed by more than one tier, so one occurrence can satisfy
  two tiers and inflate a score. `tests/.../annual/test_evidence.py` pins the tier names,
  order, priorities, values, and match policies.
- **`ANNUAL_BODY_LEXICAL_PACK.exclusion_terms` is `ANNUAL_COVER_EXCLUSION_TERMS`** (25
  entries). The quarterly and current packs have their respective form-specific exclusion sets.

## Public surface

- `AnnualReportEvidence`, `QuarterlyReportEvidence`, `CurrentReportEvidence` — the per-family evidence records, each exposing its lexical pack
- `FORM_10K_ITEMS`, `FORM_20F_ITEMS`, `FORM_10Q_ITEMS`, `FORM_8K_ITEMS` and the matching `*_DERIVED` lookup dicts
- `ANNUAL_CHECKBOX_SCHEMA`, `QUARTERLY_CHECKBOX_SCHEMA`
- `ANNUAL_BODY_LEXICAL_PACK`, `QUARTERLY_BODY_LEXICAL_PACK`, `CURRENT_BODY_LEXICAL_PACK`
- `build_taxonomy_derived(items, parts)` (`annual/taxonomy.py` only)

No command surface.

## Tests

```text
tests/domain/forms/families/annual/test_checkmarks.py
tests/domain/forms/families/annual/test_evidence.py
tests/domain/forms/families/annual/test_taxonomy.py
tests/domain/forms/families/quarterly/test_checkmarks.py
tests/domain/forms/families/quarterly/test_evidence.py
tests/domain/forms/families/quarterly/test_taxonomy.py
tests/domain/forms/families/current/test_evidence.py
tests/domain/forms/families/current/test_taxonomy.py
```

`current/` has no `checkmarks.py`, so it has no mirrored test for one either.

## Deliberate gaps

- **The checkbox schemas duplicate `domain/forms/common/schemas.py`.**
  `ANNUAL_CHECKBOX_SCHEMA` and `QUARTERLY_CHECKBOX_SCHEMA` are each defined twice. The
  definitions compare equal today and no test pins them to each other, but the copies in
  `engine/forms/cover/` are the family ones, so a divergence would be silent.
- **`current/taxonomy.py` declares `PARTS = ()`.** An 8-K has no Part structure, so
  the derived lookup's `late_parts` is empty and only item-level detection applies.
- **Triage-rule execution and exhibit delegation live in
  `engine/forms/plugins/evaluators/`**, which resolves a family through
  `common.aliases.resolve_alias`. This package supplies the declarative data the evaluators
  read and holds no execution logic.
- **No family publishes a 6-K-specific taxonomy.** `annual/` covers 10-K and 20-F and
  `current/` covers 8-K items; `resolve_alias("6-K")` returns `"6-K"`, but no
  subpackage declares items or evidence for it.