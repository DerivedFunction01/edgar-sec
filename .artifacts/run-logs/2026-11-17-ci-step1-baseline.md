# CI Step 1 — baseline under the whole instrument (generation: whole)

DRAFT — figures land as the runs complete. Final record is
committed on branch ci-step1-baseline under
.artifacts/run-logs/.

## Instrument

- Production code: main ba9f9066 (CI Step 5's landed detail
  floor: DETAIL_AGREEMENT_FLOOR 3.0 inside the agreement
  pass, ASSIGNMENT_FLOOR unmoved).
- Plus Step 0's cured collect (commit 7a3d8174), landed on
  main as 0ec6dba2 during this lane's setup; worktree HEAD
  e6c56989. The picked collect.py blob is 7835845b,
  byte-identical to the cure's (md5 d95875f4); the venue
  payload carries that same blob (verified in-archive).
- Generation label: **whole** (veto + form-test channels
  both populated). No reading in this record blends
  generations.
- Fidelity, cited not re-proven (Step 0's proof of record,
  .artifacts/run-logs/2026-11-17-ci-step0-form-test-cure.md):
  form-test points 3,092.0 cured = 3,092.0 production over
  535 probe rows, every GeometryText field equal,
  compete_filing agreeing 34,319/34,319, uncured
  reconstruction 0.0; scoped fleet gate GREEN
  (greenfield-ci-step0-gate-v3-20261117T152005Z).

## section_scopes decision

The baseline runs **scopeless**: the collect job copy calls
compete_filing(texts) with production's default scopes ().
(1) Attribution: the survivor re-closure divides by Step 5's
cured reading, which ran scopeless; adding the repo
collect's annual section_scopes() would introduce
section-scope refusals as a third delta beside the two
whole-instrument deltas and make kills unattributable.
(2) The plan defines the whole instrument as exactly the
two competition channels populated; scopes are neither.
(3) No production caller of compete_filing sets scopes, and
every sealed-lineage job copy ran scopeless. Named bound: a
scopes-on reading is a different instrument needing its own
ruling; the repo collect's scopes call is recorded as a
measurement-collect divergence, mirrored not silently
inherited.

## Step 0 bounds consumed (recorded decisions)

- closure_closed has no producer anywhere in the tree
  (production leaves it None too) — mirrored, not fixed;
  zero priced consequence.
- Placement-consistency form tests evaluate only at the
  cascade filing-level pass (classify_filing inside
  assemble stamps PlacementFacts; the competition seam
  stamps none on both surfaces).
- Fixture reconstruction hardcodes column_alignments/
  widths () and ascii_text "" (no extraction consumer
  reads them).

## Strata (drawn and sealed before any scoring)

- Universe: filing_targets of catalog snapshot
  4fb77297c5ead34b (lineage snapshot of record; a newer
  snapshot exists and was deliberately not used — changing
  the universe mid-lineage would confound seal accounting).
- Seeded order md5(accession || seed), one filing per
  (cik, report_date), dashed-accession normalization.
  Seed: ci-step1-20261117. Eras: pre2010 = 2005–2009,
  y2010s = 2010–2019, ixbrl = 2020+.
- Stratum B (10-K/10-K/A): quotas 90/330/420 = **840**,
  774 distinct CIKs. Seal:
  **5468cb92fb0c59d6350404a0e71b3fb7c88b01b411dd2d631cb342d4ae78dfa6**.
- Stratum D (10-Q/10-Q/A): quotas 120/540/660 = **1,320**.
  Seal:
  **1bedf65e6affbb7bac7be2d6906f68c64ed7afb731f2fe16bdb4f74e05ebe308**.
- Exclusion union 9,049 unique accessions: phaseB specs
  1,458; step9 population fixtures 3,000; retained corpus
  409; step11 lane-c fresh 1,320; step4 fresh-b 840 /
  fresh-d 1,320; step6 fresh-b 840 / fresh-d 1,320 (the
  Step 5 strata). Disjointness verified empirically
  post-draw: overlap 0 against every prior list, B∩D = 0.
- Sampling (lineage parameters): sampler seed 20261117;
  grouped cap 12/family/stratum, balance_sheet cap 48,
  band-stratified over (5,7.5),(7.5,10),(10,15),(15,∞);
  assembly cap 12/family/stratum; sweep 700/stratum drawn
  in-collect under sweep seed ci-step1-sweep-20261117.
- Draw route of record: DuckDB over the published extracts
  through the scheduler ops route (the repo's standing
  extracts route), executed before the venue-discipline
  correction arrived; outputs deterministic (seeded md5
  order over a pinned snapshot) and sealed on disk. Every
  subsequent script in this lane executes on fleet
  sessions (see Venue compliance).

## Protocol machinery adaptations (enumerated, this lane)

- collect_step6.py job copy: built from the cured repo
  collect with only — docstring; SWEEP_SEED/PREFIX literals
  (prefix kept "step6" so lineage machinery reads outputs
  verbatim); compete_filing(texts) scopeless per the
  decision above; 8 workers; plain summary write.
  geometry_text is the cured delegation verbatim. Diff vs
  repo collect: 41 lines, all enumerated here.
- score_step1.py: the lineage scorer's Step 4 delta read
  (hardcoded home path, unguarded) guarded — absent file
  yields empty deltas; the baseline table stands alone.
- closure_step1.py: new; survivor re-closure semantics and
  attribution precedence stated in its docstring and below.
- build_detail_slices lineage script bypassed: detail-host
  slices are emitted inside the probe jobs by
  emit_detail_slices.py, which builds each detail-claimed
  specimen's packet with the collect copy's own packet()
  over the fixture geometry — the same packet the lineage
  builder reads from collect outputs, built where the
  fixtures already are (avoids re-shipping ~590MB of
  packets; packet construction is the collect's own code).

## Runs

- Draw B (willow-fjord-34): 840/840 filings built, 59,451
  geometries, 13,431 returns, sweep 700. Draw D
  (keen-island-87): 1,320/1,320, 53,263 geometries, 20,093
  returns, sweep 700. Post-1 invariants reconciled
  (post1/invariants.json, failures []).
- Fresh probes (whole instrument, tree e6c56989): probe-b
  run greenfield-ci-step1-probe-b-20261117T212957Z (willow)
  981 specimens, detail slices 66/66; probe-d run
  greenfield-ci-step1-probe-d-20261117T211618Z (keen) 976
  specimens, detail slices 86/86, missing none.
- Survivor probes: surv-b run
  greenfield-ci-step1-surv-b-20261117T214618Z (willow) —
  targets from 67 B survivors, 137/137 fixtures, 167
  specimens, 17 detail slices; surv-d run
  greenfield-ci-step1-surv-d-20261117T210216Z (keen) —
  targets from 79 D survivors, 167/167 fixtures, 193
  specimens, 29 detail slices.
- Post-2a run greenfield-ci-step1-post2a-20261117T220524Z
  (willow): merge set-exact — claims 606/606, sweep
  1,400/1,400, missing/extra/dupes 0; 46 unclassified
  falses to the naming round. Post-2b run
  greenfield-ci-step1-post2b-20261117T223249Z (willow):
  naming round 2 empty (0 still unclassified after
  round 1). Post-2c run
  greenfield-ci-step1-post2c-20261117T224903Z (lunar):
  register/score/extensions/closure/census/detail/
  filing-features/emit-table all rc 0.
- Reader rounds (single-reader protocol): claims 606/606
  and sweep 1,400/1,400 (post-1); naming round 1, 46/46
  (zero left unclassified); detail-host, 198/198
  (correct-detail 72, wrong-host 52, not-detail 74).

## Per-family table (generation whole)

**At bar: 0 of 29** (25 families + 4 extension seats).
Precision binds nearly everywhere; recall is at or near
bar for several D-stratum families (cash_flow 1.000,
ppe 1.000, stock_comp_rollforward 0.952, balance_sheet
0.905) while their precision sits at 0.167–0.333.
Extensions: valuation_model_assumptions pooled precision
1.000 (24) with recall 0.615; warrant_activity precision
1.000 (6) with recall 0; combined_operations_ci and
shares_purchased record no claims at all (precision
undefined, recall 0). The full table is table.txt in the
lane's post2/outputs (emitted verbatim by post-2c's
emit_table.py from pricing-results.json + extensions.json
+ register-step1.json); unclassified remainder B 0.125
(n=192), D 0.116 (n=189).

## Fresh register

- Location: register-step1.json (lane home
  post2/outputs/ + worktree record copy).
- Counts: **386 false claims, unclassified 0**. Final
  classes: composition 131, statement-summary 45,
  supplemental-schedule 30, movement-detail 24,
  acquisition-detail 14, percentage-rows 13,
  provision-detail 12, segment-detail 10,
  summary-columns 9, ladder-detail 5, grant-activity 4,
  fragment 4, restatement-recast 3, index 2, furniture 2,
  plus gold:<family> misnamed-member rows (a true family
  named for 78 falses) and shape:/host-variant: rows.
  Mechanisms recorded: caption-echo 118, contested-twin
  27, stub-mass 10, mixed 7, subject-mismatch 4,
  prose-echo 3, selected-data 2, none recorded 172.
- Field set (the shared pricing base — stated for the
  Step 3/4/7/8 build lanes and the S1/S2/S3/S5/S11
  re-prices):
  - specimen_id (accession:table_index), stratum
  - claiming family on the grouped-return surface and/or
    the assembly surface (kept distinct), claim
    score/state/role/is_top (grouped), assembly family +
    mechanism
  - adjudicated verdict (true member / false +
    true_family where named)
  - final_class for falses
  - firm (cik) for firm-spread
  - detail_agreement outcome for every claimed specimen
    the probe covers (present/absent, host family, host
    label) — claimed specimens are exactly the probe's
    targets by construction (claims sample + sweep sets)
  - the Ruling 15 determination per imposter class (true
    class, authority standing, kind decision, three-bucket
    price, grade, carried-vs-new)
  - Unclaimed golds carry their sweep-key claims
    (return_families, assembly_family).

## Ruling 18 field-set dispositions (2026-11-17)

The field set = register-step1.json rows + the post-2c
companions (pricing-results, extensions, closure, census,
detail-pricing, filing-features) + the preserved bundles
(fresh/survivor probes, collect returns/assignments/
sweep-key, post-1 packets). Checked against the ruling's
named seeds:

- (a) Concept breadth, scale-invariant — largest-family
  concentration: **added**. Not a field before this ruling;
  post-2c now emits filing-features.json (filing_features.py
  over the collect-lite returns already staged for scoring):
  per filing, claims_by_family over claimed-state returns,
  largest_family and largest_family_concentration (a share,
  never a raw count standing alone). No sealed surface is
  re-read beyond what post-2c already stages; no draw or
  collect is re-run.
- (a) Section span: **named absence** at population level.
  structured_location {item, note} exists only on the
  packet population (sampled claims + sweep specimens,
  preserved in the post-1 artifacts); returns and probe
  rows carry no structured section field (a probe's
  classification evidence carries a "section=ITEM 8
  note=True" string for the winning family only). A
  population-level span needs packets for the full returns
  population, which the sealed collects did not emit.
- (b) Sparsity-robust structural legs: **carried** on the
  probed population. Probe rows carry groups[] {family,
  score, state, role, veto_flags, channels {leadin,
  form_test, veto}}, comp_scores {total, by_channel,
  evidence legs [channel, term, points]}, veto_hits per
  family {hard, scored}, classification {family, score,
  tier, evidence}, contested, genre_refusal, claims,
  assignment {family, mechanism}, detail_agreement
  {host_family, host_label} — presence/tier/form legs, not
  raw counts. Bound: the unprobed returns population
  carries only {family, score, state, role, is_top,
  claims, contested} per row.
- (c) Cross-statement ties, primaries as a set —
  co-presence: **added** in filing-features.json
  (primary_copresence_grouped and
  primary_copresence_assembly per filing for
  balance_sheet / income_statement / cash_flow).
  Numeric/relational ties (shared line values, tie-outs):
  **named absence** — no preserved surface carries
  per-filing statement values; not derivable from the
  collect surface as preserved.

Gap list — priced on adjudicated bases, not carried as
fresh field-set fields:

- Subject/bookend/movement/header pattern tiers (the
  S4-class SUBJ/SEP/HEAD legs): priced by lane extractors
  over packet text/geometry on the Step 4/5 bases; not
  fields on the fresh set. The substrate (table_text,
  caption_stack, prose, structured_location) is preserved
  only on the packet population, so the legs are
  re-derivable there and absent for the full register
  population.
- Movement/rollforward-form tiers as fields: present only
  as evidence strings inside probed specimens' comp_scores
  and classification evidence; not tier fields; absent on
  the unprobed population.
- The combination-pricing lane's per-specimen feature
  vectors (restructuring / warranty / ARO): live in that
  lane's artifacts; the fresh set carries final_class,
  mechanism, and the Ruling 15 determination per imposter
  class, not those vectors.
- Concept-breadth raw counts: deliberately not carried —
  the ruling's own form is scale-invariant; the counts
  remain derivable from the preserved returns but are not
  field-set fields.
- detail_agreement: carried (probe rows; every claimed
  specimen the probe covers) — confirmed, not a gap.
- Firm (cik): carried by derivation from the accession
  filer prefix; the census consumes it in that form.

## Ruling 15 determinations

- Intake: determinations-register.md (336/336 fresh falses
  + 832/832 sweep no-family specimens of the Step 5 cycle
  determined; cash-composition = detail-of cash_flow,
  imposters removed floor 3).
- Carried by mapping/citation: every fresh false's class
  falls in the determined vocabulary — the form classes
  (composition, statement-summary, supplemental-schedule,
  movement-detail, acquisition-detail, percentage-rows,
  provision-detail, segment-detail, summary-columns,
  ladder-detail, grant-activity, restatement-recast,
  fragment, index, furniture), gold:<family> for misnamed
  members, shape:<family> and host-variant:<family>.
- Determined new in-lane (bound first, grades stated):
  none required — no fresh imposter class outside the
  determined vocabulary was encountered; the naming
  rounds resolved all 46 round-1 unclassified falses
  inside it.

## Survivor re-closure (register-v3's 146)

- Semantics: lineage closure semantics (grouped =
  returns-presence at any score; assembly = assignment
  equality), with a claim-strength secondary reading
  (grouped score ≥ 5 or claims-list membership) reported
  per row, never blended.
- Attribution precedence: veto → genre seat → new family →
  form test (competition) → cascade channels (detail
  floor / form test) → unattributed (named). Basis per
  kill: trail (evidence in this reading's bundle) or
  elimination (the group vanished under a generation whose
  only competition delta is the named channel).
- Accounting: **146 re-read, 68 killed, 78 survivors,
  0 not probed**. Kills by mechanism: genre seat 39,
  form test (competition) 21, veto (scored) 8. Basis:
  trail 65, elimination 3. Claim-strength secondary
  reading: 0 additional kills. Survivors by family:
  aoci 22, ppe 8, income_statement 7, inventory 5,
  segment_reporting 5, stock_comp_rollforward 4, and
  27 across 13 further families; 46 survivor firms.
  Full per-row accounting: closure-step1.json.

## Residual census (firm one-off standard)

- Fresh falses (386): firm-spread in every large family —
  balance_sheet 73 specimens / 43 firms / largest share
  0.16; tax_reconciliation 21/15/0.14; cash_flow 19/14/
  0.16; deferred_tax 19/13/0.32; income_statement 19/14/
  0.16; stock_comp_rollforward 19/17/0.16;
  equity_statement 18/11/0.28; lease_maturity 18/13/0.22.
- Still-standing survivors (78): aoci 22/16/0.14, ppe
  8/8/0.12, income_statement 7/6/0.29, segment_reporting
  5/4/0.40 (the largest share anywhere in the census).
- Verdict: **the residual fails the firm one-off standard
  on the concentration leg everywhere** — no family's
  residual is specimen-thin, single-firm concentrated,
  and feature-free; the mass is general (composition /
  statement-summary / caption-echo led) and stands as
  priced work for the Step 3/4/7/8 fan-out, not as
  acceptable one-offs. Per-specimen lists:
  census-step1.json (fresh_false_claims + v3_survivors).

## Detail side computation (breakdown/detail)

- P1 (88 Step 5 imposter pairs): 38 still falsely claimed
  under the whole instrument; 1 detail-claimed.
- P2 (167 Step 5 sweep detail-classed): agreements fired
  31, detail-claimed 0 — the whole instrument's assembly
  never lands on the claimed host for this population.
- P3 (301 fresh sweep detail-classed): 42 detail-claimed
  (claim rate 0.140), host-adjudicated 42, host-correct
  18 (correct share of population 0.060).
- Targeted host precision over all adjudicated detail
  claims: 48/153 = 0.314. Claims by host: balance_sheet
  69, income_statement 51, cash_flow 28,
  equity_statement 5. Full rows: detail-pricing.json.

## Caveats

- Single-reader adjudication throughout (lineage
  protocol); sample caps bind per family (grouped 12,
  balance_sheet 48, assembly 12 per stratum) — thin bases
  are printed, never smoothed.
- Scorer diagnostics (no classification impact; register
  unclassified stays 0): pricing-results carries 337
  record problems — 172 falses whose reader verdict
  recorded no false_claim_mechanism, plus rows flagged
  for the mechanism token 'caption-echo' sitting outside
  the scorer's mechanism vocabulary in one surface — and
  13 vocabulary notes where readers named extension
  families (valuation_model_assumptions, warrant_activity)
  as true_family; those specimens are scored in
  extensions.json.
- The payload tree for post-2c's measurement import
  excludes bulk data files (*.parquet, *.gz, __pycache__)
  the measurement module never reads — code and package
  JSON only; the exclusion is recorded here because the
  draw payloads carried the full tree.
- probe-d.jsonl's re-fire sha differs from its first
  attempt at identical size (4,294,869 bytes) and specimen
  count (976); downstream consumption is parsed-JSON, so
  the reading is unaffected; noted, not chased.

## Venue compliance

- Draw + disjointness: extracts route via the scheduler
  ops route, before the venue correction arrived (route of
  record stated above).
- Everything after: fleet sessions only, detached and
  polled, caller edgar-successor:greenfield-followup.
- Local activity: file authoring, the venue funnel, and wb
  record writes through the ops route (orchestration).
  Under the tightened clause (2026-11-17 11:20 EST), no
  local code execution at all; two py_compile syntax checks
  of authored wraps earlier in the session pre-dated the
  tightened wording.
- Launch history: five manifest upload-verify failures on
  the pre-rollover set (channel fault; runs
  greenfield-ci-step1-b-20261117T160419Z,
  greenfield-ci-step1-b-20261117T161258Z,
  greenfield-ci-step1-d-20261117T160133Z [stale lease —
  session gone], greenfield-ci-step1-d-20261117T160853Z,
  greenfield-ci-step1-d-20261117T162054Z); fleet rollover
  12:00 EST 2026-11-17; draws re-fired on the new set:
  <run ids>.
