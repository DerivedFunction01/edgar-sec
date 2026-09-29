# `edgar_sec/engine/tables` — ASCII/HTML table resolution and byte-exact table protection

Decides where a table starts and stops in plain text, refuses the shapes that only look like
tables, and guarantees that a `<TABLE>...</TABLE>` block passes through every later stage
untouched. It owns the sentinel-masking protocol that makes the whole protection guarantee
possible.

The HTML→ASCII rendering engine itself is the sub-package `edgar_sec/engine/tables/ascii_html/`,
documented separately.

## Purpose

Plain-text filings contain two kinds of tabular material: tables that are already tagged
(`<TABLE>...</TABLE>` with `<S>`/`<C>` cell markers, preserved from the SGML era) and tables that
are pure alignment — a stub, a gutter, and a column of right-aligned numbers. This package
handles the second kind's *boundaries* and both kinds' *protection*.

Three questions, three modules:

1. **Where does this untagged table begin and end?** `resolver.py` grows a confirmed
   `TAG_AND_PRESERVE` decision outward — absorbing header prefixes, bridging blank lines, page
   markers, and structural section labels, and absorbing the final total row.
2. **Is this actually a table?** `table_policy.py::is_tableish_block` and the rule engine's
   geometry gates answer yes; `false_tables.py::is_false_grid` answers the opposite question for
   rendered HTML.
3. **How do we guarantee nothing inside a table changes?** `protection.py` masks the span
   behind `__SEC_TBL_{n}__` and restores it exactly.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `protection.py` | The masking protocol. `TableSpan` (with `.complete`, `.line_ranges`), `find_table_spans`, `mask_tagged_tables`, `restore_tagged_tables`, `ensure_table_tag_boundaries`, `strip_table_wrapper_tags`, and the `ProtectedText` boundary object that applies a callable to text outside, or to one span of, a protected region. |
| `resolver.py` | Single-forward-pass table region resolution. `resolve_table_regions` coalesces adjacent `TAG_AND_PRESERVE` decisions and applies `_validate_table_discipline`, which downgrades any candidate table lacking two numeric rows or two shared columns to `PRESERVE` (`resolver.py:44-53`). |
| `structural.py` | The three boundary predicates: `is_header_prefix` (a caption/units/period row immediately above a table), `is_structural_table_bridge` (a heading-shaped label between two halves of one statement), `is_structural_table_tail` (a final aligned total or double-underline). Plus `PERIOD_SUBHEADING_RE`, `UNITS_LABEL_RE`, `COLUMN_YEAR_ROW_RE`, `COLUMN_DASH_RULE_RE`. |
| `table_policy.py` | The table/prose unification policy. `is_tableish_block` (the pre-relaxation table test), `split_structural_table_intro` (separate a narrative lead-in from the table that follows it), `unify_table_prose` (rejoin a table with adjacent prose only at a safe sentence boundary), `is_table_row_continuation` (a wrapped row's numeric columns still align). |
| `numeric_cells.py` | Financial cell vocabulary. `is_numeric_cell` recognises a number with an optional currency symbol, sign, percent, or range; `numeric_cell_starts` reports where numeric cells begin after a column gap; `FINANCIAL_PLACEHOLDERS` covers `—`, `$-`, `n/a`, `nil`, and their currency-decorated forms. |
| `currencies.py` | `MAJOR_CURRENCIES` (nine currencies with names, symbols, and prefix/suffix placement) and the derived `PREFIX_CURRENCY_SYMBOLS`, `SUFFIX_CURRENCY_SYMBOLS`, `ALL_CURRENCY_SYMBOLS` frozensets. |
| `false_tables.py` | False-table rejection for rendered HTML. `is_false_table` / `is_false_grid` decide that a layout-only table is really a bulleted or numbered prose list; `unwrap_grid` reconstructs the prose; `cleanup_false_tables` applies the verdicts across a document without dropping surrounding text. Handles three grid shapes: 3+ effective columns (ordered prose grid with monotonic outline markers), 2 columns (TOC rows, item references, lead-in + bullets), and 1 column. |
| `toc.py` | Table-of-contents primitives. `looks_like_toc_row`, `looks_like_toc_tabular`, `looks_like_toc_text`, `is_toc_row`, plus `RE_PART_REFERENCE`, `RE_ITEM_REFERENCE`, `RE_TOC_LEADER`, `PART_HEADING_RE`, `TOC_ITEM_RE`. Also the home of the known trap: `RE_PAGE_NUMBER_SUFFIX` matches a trailing Roman numeral, so `looks_like_toc_row("PART I")` is `True` (see `roadmap/refactor_v2/phase_2_5/04_engine_tables_and_forms.md` §5). |
| `patterns.py` | The owner of table pattern vocabulary: `CAPTION_RE`, `TABLE_TAG_RE`, `RE_TABLE_BLOCK`, `S_MARKER_RE`, `C_MARKER_RE`, `HTML_TAG_RE`, `WHITESPACE_RE`, `NUMERIC_RE`, `PAREN_SPACES_RE`, `FOOTNOTE_RE`, `HIDDEN_ELEMENT_STYLE_RE`. |
| `ascii_html/` | The 16-module geometry-first HTML→ASCII renderer. See `ascii_html/README.md`. |

## Contracts

- **Byte-for-byte table protection is the package's core guarantee.** `mask_tagged_tables`
  replaces each span with `__SEC_TBL_{n}__` and `restore_tagged_tables` reinstates the exact
  original text. Restoration is *checked*: if the set of sentinels seen does not equal the set
  of spans supplied, `restore_tagged_tables` raises `ValueError` rather than returning a
  document that quietly lost a table (`protection.py:180-184`).
- **Masking is a no-op on a document that contains no tables, and on one that already contains
  a sentinel.** `find_table_spans` returns `()` when `SENTINEL_PREFIX` is present
  (`protection.py:126`), so a double-mask corrupts nothing.
- **Every other stage must mask before rewriting prose.** `edgar_sec/engine/document/html_cleaner.py`,
  `edgar_sec/engine/document/whitespace.py`, and `edgar_sec/engine/reflow/engine.py` all import
  `mask_tagged_tables`/`restore_tagged_tables` from this module. That is the enforcement
  mechanism, not a convention.
- **Tagging is a *bounded* claim.** A block is only wrapped in `<TABLE>` when the discipline
  gate is satisfied — at least two numeric rows or two shared numeric columns
  (`resolver.py:41-53`). A candidate that overlaps an already-protected span is downgraded to
  `PRESERVE` with `protected_table_overlap` evidence (`resolver.py:32-40`).
- **The default answer is preserve.** `RuleEngine._default_rules()` in
  `edgar_sec/engine/reflow/rules.py` terminates at `default_preserve_ambiguous` with the stated
  rationale "to guarantee zero table corruption". Every uncertainty resolves toward leaving the
  block alone.
- **Merging is evidence-gated, not proximity-gated.** `resolve_table_regions` only absorbs a
  neighbouring block when it is a header prefix, a blank line within `max_blank_lines`, an
  all-page-marker span, a structural bridge, a structurally aligned continuation, or a
  structural tail — and it lowers `confidence` with every absorption (`min(..., 0.75)` at
  `resolver.py:162`, `:213`).
- **Layer discipline.** Imports are `foundation` and sibling `engine.reflow` only; no upward
  dependency. `false_tables.py` imports `ascii_html.model` under `TYPE_CHECKING` and uses a
  string annotation, so importing it does not pull in the renderer (`false_tables.py:32-33`).

## Public surface

- `TableSpan` — one protected span with `.complete` and `.line_ranges`.
  `edgar_sec/engine/tables/protection.py:35`.
- `SENTINEL_PREFIX` / `SENTINEL_SUFFIX` — `__SEC_TBL_` / `__`. Every consumer treats whitespace
  adjacent to these as a line separator. `edgar_sec/engine/tables/protection.py:30-31`.
- `mask_tagged_tables` / `restore_tagged_tables` — the masking pair.
  `edgar_sec/engine/tables/protection.py:149` and `:166`.
- `find_table_spans` — locate every complete or unterminated `<TABLE>` span in source order.
  `edgar_sec/engine/tables/protection.py:124`.
- `ensure_table_tag_boundaries` — put restored `<TABLE>`/`</TABLE>` tags on standalone lines
  without touching the contents. `edgar_sec/engine/tables/protection.py:194`.
- `strip_table_wrapper_tags` — remove the wrapper elements, keep the table body.
  `edgar_sec/engine/tables/protection.py:188`.
- `ProtectedText` — immutable protected-text boundary; `transform_outside(func)`,
  `transform_span(index, func)`, `.masked`, `.spans`, `.complete_spans`, `.unterminated_spans`.
  `edgar_sec/engine/tables/protection.py:54`.
- `resolve_table_regions` — resolve and coalesce table boundaries in one forward pass.
  `edgar_sec/engine/tables/resolver.py:56`.
- `is_header_prefix` / `is_structural_table_bridge` / `is_structural_table_tail` — the three
  boundary predicates. `edgar_sec/engine/tables/structural.py:117`, `:174`, `:200`.
- `is_tableish_block` — the pre-relaxation aligned/numeric table test.
  `edgar_sec/engine/tables/table_policy.py:102`.
- `split_structural_table_intro` — separate a narrative lead-in from the table below it.
  `edgar_sec/engine/tables/table_policy.py:76`.
- `unify_table_prose` — rejoin a table to adjacent prose only at a safe sentence boundary.
  `edgar_sec/engine/tables/table_policy.py:124`.
- `is_table_row_continuation` — a wrapped row's numeric columns still align.
  `edgar_sec/engine/tables/table_policy.py:175`.
- `is_numeric_cell` / `numeric_cell_starts` / `is_financial_placeholder` / `is_prefix_token` —
  the financial cell recognizer. `edgar_sec/engine/tables/numeric_cells.py:82`, `:92`, `:77`, `:88`.
- `ALL_CURRENCY_SYMBOLS` / `PREFIX_CURRENCY_SYMBOLS` / `SUFFIX_CURRENCY_SYMBOLS` /
  `MAJOR_CURRENCIES` — currency vocabulary. `edgar_sec/engine/tables/currencies.py:64-78` and `:7`.
- `is_false_table` / `is_false_grid` / `unwrap_grid` — false-table rejection and prose
  reconstruction. `edgar_sec/engine/tables/false_tables.py:301`, `:216`, `:349`.
- `cleanup_false_tables` / `cleanup_false_tables_with_metadata` — document-level unwrapping.
  `edgar_sec/engine/tables/false_tables.py:456` and `:380`.
- `looks_like_toc_row` / `looks_like_toc_tabular` / `is_toc_row` / `looks_like_toc_text` — TOC
  predicates. `edgar_sec/engine/tables/toc.py:40`, `:18`, `:28`, `:53`.
- `RE_PART_REFERENCE` / `RE_ITEM_REFERENCE` / `RE_TOC_LEADER` / `PART_HEADING_RE` /
  `TOC_ITEM_RE` — TOC vocabulary. `edgar_sec/engine/tables/toc.py:9-15`.

## Tests

- `tests/engine/tables/test_protection.py` (28 lines) — masking, restoration, `ProtectedText`.
- `tests/engine/tables/test_resolver.py` (41 lines)
- `tests/engine/tables/test_structural.py` (41 lines)
- `tests/engine/tables/test_table_policy.py` (45 lines)
- `tests/engine/tables/test_numeric_cells.py` (31 lines)
- `tests/engine/tables/test_currencies.py` (20 lines)

`tests/engine/tables/conftest.py` is absent; there is no shared fixture setup, because every
test in this package is a pure-function test.

## Deliberate gaps

- **There is no test for `false_tables.py`, `patterns.py`, or `toc.py`.** The mirrored
  requirement in `AGENTS.md` §6 says one test file per source module; these three have none.
  `toc.py` is exercised only indirectly by
  `edgar_sec/engine/forms/cover/closing.py` (which imports `is_toc_row`) and by
  `false_tables.py` (which imports `looks_like_toc_row` / `looks_like_toc_tabular`), and
  `false_tables.py` is exercised only through `edgar_sec/engine/tables/ascii_html/__init__.py`,
  which itself is untested. Their behaviour is not pinned by a direct test.
- **There is no test for the `ascii_html/` sub-package at all** — no
  `tests/engine/tables/ascii_html/` directory exists. See `ascii_html/README.md` for what that
  costs.
- **`patterns.py` is largely unconsumed.** Of its eleven compiled patterns, only three have any
  importer in the tree: `RE_TABLE_BLOCK` and `FOOTNOTE_RE` (from `false_tables.py:16`) and
  `HIDDEN_ELEMENT_STYLE_RE` (from `ascii_html/css.py:15`). `CAPTION_RE`, `TABLE_TAG_RE`,
  `S_MARKER_RE`, `C_MARKER_RE`, `HTML_TAG_RE`, `WHITESPACE_RE`, `NUMERIC_RE`, and
  `PAREN_SPACES_RE` have zero consumers in `edgar_sec/` or `tests/`. They are the vocabulary a
  caption/`<S>`-marker consumer would need; today nothing consumes them. (Note the module
  docstring calls this "the owner of table pattern vocabulary" — that ownership is nominal, not
  load-bearing.)
- **`looks_like_toc_text` has no caller.** It is exported and correct, but nothing in
  `edgar_sec/` calls it; `engine/forms/cover/body_search.py` uses its own strict/loose pair
  instead.
- **`ProtectedText` has no production caller.** Only `tests/engine/tables/test_protection.py`
  constructs one. The masking function pair (`mask_tagged_tables` /
  `restore_tagged_tables`) is what the rest of the tree uses.
- **v1's 914-line `defs/sec_forms/cover/toc/` subsystem was only partially substituted.** The
  TOC *span finder* has no v2 home; `engine/tables/toc.py` provides the row-level *primitives*
  only. `engine/forms/cover/boundary.py::TOC_TRANSITION` uses a heading-based path instead, so
  the signal fires one step later and without v1's confidence refinement. This is recorded in
  `roadmap/refactor_v2/phase_2_5/04_engine_tables_and_forms.md` §4.3.
- **No financial table *semantics*.** Nothing here knows that a column headed "Total" is a
  total, that a double rule is a subtotal, or that a statement has assets then liabilities then
  equity. The package decides boundaries and alignment; it does not read tables. (v1's
  `defs/taxonomy/` was a financial *table* classifier — a naming collision with v2's
  `edgar_sec/domain/taxonomy/`, which is entity vocabulary. The two are unrelated; the v1
  classifier has no v2 home.)
- **`ReflowPolicy` lives here but is not table code.** `edgar_sec/engine/tables/table_policy.py`
  and `resolver.py` both take a `ReflowPolicy`, whose definition is in
  `edgar_sec/engine/reflow/types.py:20`. This is a deliberate one-way dependency
  (`reflow` → `tables` in the driver, `tables` → `reflow.types` for the type only), not an
  import cycle: `reflow/types.py` imports `TableSpan` from `tables/protection.py`, and
  `tables/resolver.py` imports `_compute_features` from `reflow/features.py`.
- **No entry point.** This package has no CLI. Its only consumers are
  `edgar_sec/engine/reflow/engine.py`, `edgar_sec/engine/document/html_cleaner.py`,
  `edgar_sec/engine/document/whitespace.py`, and
  `edgar_sec/engine/forms/`.
