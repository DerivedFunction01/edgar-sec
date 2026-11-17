# CI Step 0 — form-test channel cure and channel census: record

Lane: CI Step 0 (todo ci-form-test-cure-census), continuous-
improvement plan Step 0. Measured base 6be5f9a5; cure tree
124cb15035f81b42ba9e05b52b385cdf4bd3779b (worktree branch
ci-step0-cure, local commit 7a3d8174, never pushed — main lands).

## Findings

- **The cure is one construction, not a patch per channel.**
  `collect.py`'s `geometry_text` now returns
  `geometry_text_from_table(structure_table(_context(g)))` — the
  production seam's own construction over the fixture-reconstructed
  table the collect already built for its assembly/toc instruments.
  Every channel, `form_tests` included, is the production stage's
  outcome by construction (+2/−44 lines, one file).
- **Fidelity: exact, not approximate.** On the Step 5 probe
  populations (register-v3 falses + P1 pairs + P2 sweep specimens),
  the cured collect's text equals the production seam's on every
  one of the 28 `GeometryText` fields, every specimen (stratum B:
  261/261, form-test outcomes 11,223 with 1,374 passed on both
  sides, form-test points 1,459.0 = production's 1,459.0; stratum
  D: 274/274, outcomes 11,782 with 1,549 passed on both sides,
  points 1,633.0 = production's 1,633.0). Combined: 535 measured
  rows over 534 distinct targets (filing 0001193125-05-054130
  carries two geometries at index 15 — the duplicate-geometry
  quirk of record in STATE-step5; both measured, both equal),
  23,005 outcomes, 2,923 passed, 3,092.0 form-test points.
  `compete_filing` over the whole filings carrying the targets
  agrees on claims/contested/groups for every geometry
  (B: 20,501/20,501; D: 13,818/13,818; combined 34,319/34,319,
  zero disagreements). The uncured reconstruction (same text,
  `form_tests` emptied) contributes **0.0 form-test points on
  every specimen** — the dark channel, shown dark.
- **The pre-cure construction diverged on seven more channels**
  (specimens differing from the seam; B n=261 / D n=274):
  `note_title` 163/232 (sourced from `structured_location` vs
  production's `preceding.note.title`), `stubs` 112/106 (raw
  first cells vs structured row labels), `caption` 103/91 (no
  parsed titles; `lead` and `notehead` inherit the same
  counts), `grid_text` 259/272 (unnormalized join; its sole
  consumer normalizes, so veto outcomes were unaffected —
  Step 5's 534/534 hits agreement stands), `headers` 254/270
  (never populated — the derivatives gate's subject text was
  dark in the tree collect too), `form_tests` 261/274
  (always empty).
  `section_form`/`section_part` were also unpopulated in the
  old construction, but the production values over this
  population are likewise `None` (0 differing) — populated by
  construction now, value as production reads it.
- **The verdict's caption-title bound is retired.** Step 5's
  record named the caption-title component of `lead` a fixture-
  format bound ("no collect built on these fixtures can
  reproduce it"). Measured here: the titles are parsed by
  `structure_table` from the fixture's own rows — the
  reconstruction the collect already ran — so the component is
  fixture-carried; the bound priced the hand-built
  construction, not the format. Cured `lead` equals production
  `lead` on 535/535 measured rows.

## The cure

`edgar_sec/tools/measurement/collect.py` only: `geometry_text`
delegates to `geometry_text_from_table(structure_table(
_context(g)))`; the hand-built field assembly and its now-unused
imports (`heading_text`, `leadin_segment`, `lead_title_text`)
are deleted. No other seam changes: `run_filing`, `packet`,
the sweep, and the scorer-facing outputs are untouched. Cost:
`structure_table` now runs twice per geometry in `run_filing`
(once for the text, once for the toc read) — a measurement-
collect runtime cost, accepted; no production path changes.

## Channel census

Proof standard: per input, the cured collect's population is
the production construction itself (same function over the
same reconstructed table/context), and the probe above
measured field-level equality against the seam on the probe
population. Typing per Rulings 12/13: **core-capable** = the
channel can carry a family's defining (core) points;
**rank-bearing** = it can carry a family's highest-ranked
(core-defining) evidence; where a family's Ruling 11 core
determination is not yet of record, the mark is *pending
determination* — never asserted.

### Competition surface — `GeometryText` fields

| Input | Consumer | Populated | Typing (Rulings 12/13) |
|---|---|---|---|
| caption | signature terms; detail signatures; ladder direction | yes — seam construction | supporting-only (vocabulary/framing mass) |
| leadin | signature terms | yes | supporting-only |
| notehead | signature terms | yes | supporting-only |
| lead_title | signature terms; derivatives gate framing | yes | supporting-only |
| stubs (stub_text) | signature terms; detail signatures; ladder direction; derivatives gate | yes — structured row labels | supporting-only (vocabulary/profile mass) |
| form_tests | `score_geometry` form_test term | yes — **the cured channel** (`evaluate_form_tests` over the reconstructed TypedTable) | **core-capable; rank-bearing: pending determination** per family/test — kinds encoding a defining form (measure_set for the measure-set seats; primary_statement_seat and walk tests for the primaries) are the candidates the family lanes' Ruling 11 determinations settle. Placement-consistency outcomes are unevaluable here, exactly as in the production seam (no caller-stamped PlacementFacts in `geometry_text_from_table`) |
| lead | term vetoes (lead channel) | yes | no claim points — negative evidence only |
| grid_text | term vetoes (body channel) | yes | no claim points — negative evidence only |
| headers | derivatives gate subject text (`DerivativesText.from_geometry`) | yes — zone construction over the reconstructed table (was dark) | typing pending determination (Step 2 lane's Ruling 11 act types the derivatives gate evidence); carries gate points only via that gate |
| closure_closed | `compete` closure corroboration | **no producer exists** — the production seam leaves it `None` too; see bounds | supporting by name (corroboration points) where a producer ever stamps it |
| note_title | compete_filing inheritance/tie grouping | yes — `preceding.note.title` (source corrected) | supporting-only (context channel points lend another geometry's evidence) |
| section_item | inheritance same-home; section-scope refusal | yes — `preceding.section.item` (source corrected) | no claim points — grouping/refusal input |
| section_form | section-scope refusal (`genre_refusal`) | yes — `preceding.section.form` (was dark; production value over the probe population is `None`, as is the seam's) | no claim points — refusal input |
| section_part | section-scope refusal | yes — `preceding.section.part` (was dark; same `None` note) | no claim points — refusal input |
| section_title | section-scope refusal (title decides ahead of the item map) | yes | no claim points — refusal input |
| in_toc_span, in_closing_span, closing_kind, front_matter, note_seated, numeric_cells, data_rows, grid_rows, max_row_cells, index_named_share, page_ref_share, page_ref_only, exhibit_stub_share | genre seat refusal (`GenreFacts.from_geometry`) | yes — fixture fields, `from_record` source | no claim points — refusal inputs |
| scopes argument | `compete_filing(..., scopes=section_scopes())` | yes — the annual forms' declared scopes, the sealed protocol's source | no claim points — refusal input set |

### Cascade surface — TypedTable via `_context` + `structure_table`

The collect's assembly instrument runs `assemble(contexts)`,
which is `structure_table` + `evaluate_math` + `classify_filing`
+ arbitration — the production cascade itself over
`TableContext.from_record` records. Every cascade input is
therefore populated by the same construction production uses
over corpus records:

| Input | Read by | Populated |
|---|---|---|
| grid rows (`context.rows`), header_row_count, confidence | `structure_table`, math, form tests | yes — fixture record fields |
| caption_stack, prose_before/after | context, caption parse, heading/leadin derivation | yes |
| preceding.section (item/title/form/part), preceding.note (number/label/title) | section scopes, note grouping | yes |
| scale, location, breaks, issues, label, region/region_path, source_document, seat | context carriage | yes — carried, per `from_record` |
| in_toc_span, in_closing_span, closing_kind, front_matter, numeric facts, shares | genre seat, toc gate | yes |
| TypedTable rows (label/values/kind), caption (titles/consumed_rows), periods, header_rows | classify_filing, form tests, math, detail agreement | yes — produced by `structure_table` over the rows above |
| PlacementFacts (filing constellation) | cascade filing-level `evaluate_form_tests(..., placement=facts)` at classify.py:636 | yes — stamped by `classify_filing` itself inside `assemble`; the per-table call (classify.py:440) and the competition seam stamp none, on both surfaces alike |

Cascade evidence channels and their typing: `form_test`
(core-capable — the same `evaluate_form_tests`; the detail
value agreement outcome is breakdown/detail's core point per
the adopted plan's Step 5 text; other families' typing pending
their Ruling 11 determinations), `math` (`evaluate_math`
closing arithmetic — core-capable for the primaries,
rank-bearing pending Step 3's census), measure-set seats
(core-capable, pending Step 6's determinations), `landmark`,
`structure`, `shape`, `sequence`, `seat`, `note`, `context`
(supporting/corroboration class), `genre_refusal` (negative).

## Named bounds

1. **closure_closed has no producer.** `compete` reads it; no
   construction in the tree stamps it — not the production
   seam, not the collect. The channel is dark in production
   itself, so the collect faithfully mirrors a dark channel;
   priced consequence for measurement fidelity: none (both
   sides dark, 0 differing on the probe). Flagged to the
   coordinator as a production-side observation: a scored
   corroboration term no construction feeds.
2. **Fixture-reconstruction bounds (vs a live render).**
   `_context` hardcodes `ResolvedGrid.column_alignments` /
   `column_widths` to `()` and `TableRenderResult.ascii_text`
   to `""`. No extraction consumer reads alignments/widths
   (ascii_html diagnostics only), and `ascii_text` feeds live
   context building (`context_production`), whose derived
   fields the fixture record already carries — so no
   classification channel depends on either over fixtures.
   Priced consequence: none measured; named so a future
   consumer of either field re-opens this census first.
3. **Placement-consistency at the competition surface** is
   unevaluable by construction (no stamped facts in
   `geometry_text_from_table`) — a property of the production
   seam, mirrored exactly, not a collect gap. The cascade's
   filing-level pass stamps the facts and fires it.

## Verification

- Fidelity probe (venue, caller edgar-successor:
  greenfield-followup, reusing the Step 5 draws' persisted
  workspaces): runs greenfield-ci-step0-fidelity-b-
  20261117T143450Z (river-talon-95, probe_rc 0) and
  greenfield-ci-step0-fidelity-d-20261117T143830Z
  (lilac-laurel-87, probe_rc 0); probe script + outputs in
  the lane home (~/workspace/greenfield-ci/step0/) and the
  venue results.
- Scoped gate (venue, rapid-ridge-97): snapshot bundle of
  the cure tree (snap f97e8d35269a74b488ae076554e26815c5a91
  e13, tree asserted 124cb150…, sha256 ead0ba017d8982db0c4
  ad99a66a05ce4f6cc86a775cca4178715d7cbfe7709b3,
  105,631,473 B), tree identity verified venue-side before
  any check ran.
  - v1 (run greenfield-ci-step0-gate-20261117T144202Z):
    failed before the check — no seeded repo venv at
    /content/edgar-sec/.venv on that session. A venue-seed
    fact, not a tree finding.
  - v2 (run greenfield-ci-step0-gate-v2-20261117T145608Z;
    the launch call's echoed id T150108Z never registered a
    run record — the venue-side run of record is T145608Z):
    tree asserted, **format clean (2,903 files), lint clean,
    policy scanners 30/30 clean** — and the pytest leg died
    in collection, root-caused below, check_rc 3.
  - **Plan verify-line defect (flagged to the coordinator):**
    the plan's verify command, `check.py
    edgar_sec/tools/measurement/collect.py`, hands pytest a
    source module as an explicit target; pytest imports it
    as a test module and `collect.py`'s module-level
    `CONFIG = load_config()` raises SystemExit (no `--config`
    in argv), killing every xdist worker in collection —
    0 items, INTERNALERROR. This is pre-existing: the base
    tree's `collect.py` has the same import-time config load,
    so the literal verify command cannot pass on any tree.
    The gate of record therefore runs the mirrored test
    path, `check.py tests/tools/measurement/
    test_measurement.py`, which is check.py's own scoped
    form for this module.
  - v3 (run greenfield-ci-step0-gate-v3-20261117T152005Z):
    same bundle/tree, mirrored test path, Python 3.12 venv
    built draw-style (uv venv + `tree[dev]`) → **GREEN:
    check_rc 0** — tree asserted 124cb150…, format clean
    (2,903 files), lint clean, scanners 30/30 clean, pytest
    11/11 passed (tests/tools/measurement/
    test_measurement.py, Python 3.12.3, 8 workers).
