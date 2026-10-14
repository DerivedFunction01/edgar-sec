# XBRL Engine v3 — Audit Findings and Strict Validation Plan

| | |
|---|---|
| **Subject** | `declarative_xbrl_engine_v3_clean_repo.zip` (coding-agent output) |
| **Method** | Extracted, ran `verify.sh`, read source, tested data/gold/KB relationships |
| **Related** | `xbrl_declarative_solver_spec.md` (§9 evaluation, §15 knowledge model, Part I) |
| **Limitation** | My sandbox cannot reach SEC servers. Real-data checks in this document use the web search tool and my own knowledge; the plan below must be executed on a machine with SEC access. |

---

## 1. Verdict in one paragraph

v3 fixes most of the v2 problems (it runs end-to-end, git is clean, sources are real filing URLs, values I spot-checked look authentic, hint fields are gone from facts, goals are 19 lookups and 59 derived out of 78). But the evaluation is still **in-sample and self-graded**: the corpus, the gold labels, the lexicon and the solver were all written by the same agent in the same pass, and the facts are typed Python literals rather than parsed from XBRL. "100% on holdout" therefore shows the code reproduces what its author intended on 355 hand-entered facts. It is not evidence of generalization.

## 2. What improved (verified)

| Check | Result |
|---|---|
| `bash verify.sh both` from a fresh copy | Runs end-to-end, no hardcoded paths |
| `git fsck --full` | Clean (only deleted `__pycache__` shows in status) |
| Source URLs | 30 distinct filing URLs; no `company_tickers.json` |
| MSFT FY2024 product revenue | Matches the filing (Server $97,726M, Office $54,875M, Windows $23,244M); the filing's own table agrees with these figures |
| GOOGL/AAPL FY2024 headline figures | Match my knowledge of the filings (e.g. revenue 350,018 / 391,035) |
| Hints in solver facts | No `parent_measure_hint`, `calc_weight`, `notes` fields in facts |
| Goal specs | `allowed_nodes` is identical for a given goal name across all firms (53 goal names, 0 varying), so goals are firm-agnostic |
| Cross-solver copying | Gone (v2 copied another solver's answer on 93/857 goals) |
| Per-fact placement | Not a trivial copy of input calc arcs: arc parent equals the gold node for only 51 of 148 arc-bearing facts |

## 3. Shortcuts that remain

| # | Finding | Evidence | Why it matters |
|---|---|---|---|
| S1 | **Corpus is hand-typed, not ingested.** 30 filings, 355 facts, written as `add_fact(...)` literals; no network fetch, no XBRL instance/linkbase parser | `build_real_sec_corpus.py` (1,110 lines of literals) | No real contexts, units, duplicates, extension elements, or calc/pres linkbases; transcription errors possible; cannot scale |
| S2 | **Gold labels are written by the same author, in the same call, as the fact.** `add_fact(..., gt_target_node, gt_weight, gt_tier)` | same file, lines ~269–400 | Gold is not independent: same brain wrote facts, labels, lexicon, solver. Separate JSON files give an appearance of separation only |
| S3 | **Solver outputs match authored gold tiers exactly.** Solver tier counts 328/10/4/13 equal the authored gold counts; abstentions (13) are exactly the 13 authored `U3` facts | `section9_evaluation_summary.json` vs `ground_truth_oracle.json` | Signature of tuning until output equals gold on this corpus (overfit to 355 facts) |
| S4 | **Calc arcs are authored per fact.** 148/355 facts (42%) have an arc supplied as solver input; the "no arc on extensions" condition is the author's choice for 7 named tags | `xbrl_linkbases.json`; README item 3 | Real extension tags often appear in the filer's own calc linkbase; the hard case is staged, not sampled |
| S5 | **The "frozen KB" freezes little.** `kb.freeze()` hashes 61 rules + 55 relations after running the solver on seed facts; I found no code that *learns* from seed labels. The lexicon (15 heads, 32 modifiers, parser rules) is authored in code by someone who had seen all 30 filings | `kb_evidence_and_backoff.py`, `identity_oracle.py` L243–251 | The seed/holdout split cannot protect against vocabulary written with knowledge of the holdout. 27% of holdout tokens (25/93) never appear in seed qnames; 9 of those 25 (e.g. *Sales*, *Dividend*, *Financial*) are already in the authored vocabulary |
| S6 | **Holdout is tiny and author-picked.** 15 firms, 85 facts, 31 goals; firms chosen in pairs within each sector, almost all FY2024 | corpus builder; fact counts | 0 failures in 31 trials only bounds the true failure rate at ≈ 3/31 ≈ 10% (95% upper bound). No cross-time, cross-size, or random-sample test |
| S7 | **Metric definitions flatter the result.** Fact precision and coverage are both 99.71 because they share a denominator (authored "placeable" facts); authored `U3` facts are excluded from the denominator; abstentions never count against goal coverage | `identity_oracle.py` L159–171 | Cannot see risk/coverage trade-offs or abstention quality |
| S8 | **The "independent" engines share code.** In-memory and SQLite solvers import the same parser/KB modules | `in_memory_and_sql_solver.py` | Agreement shows implementation parity, not independent correctness |
| S9 | **Identity checks test the typing, not the solver.** The 15 conservation identities are evaluated on the typed input facts | `accounting_identity_oracle_checks.csv` | Useful as a data sanity check, but they say nothing about classification accuracy |
| S10 | **Hint hygiene is a deny-list.** The input guard rejects a fixed set of forbidden key names | `identity_oracle.py` L33, solver L80 | Any new leaky field passes. Needs an allow-list schema |
| S11 | **Ablation baselines are weak.** The "1D lookup" baseline is written by the same author and has no independent reference (e.g. a published mapping table) | `ablation_study_section9.csv` | The 60% vs 100% comparison is not a fair baseline |
| S12 | **Speed claims are not meaningful** at 355 facts | timing fields | Drop from headline claims |

## 4. Strict rules (apply to every future version)

Each rule has an **enforcement check** so that it fails a build rather than relying on discipline.

### 4.1 Data

| ID | Rule | Enforcement |
|---|---|---|
| D1 | The corpus is **parsed from real filings** (XBRL instance + `_cal`, `_pre`, `_def`, label linkbases), never typed in code | Corpus builder takes filing URLs only; unit test fails if any fact lacks a `source_location` (file + context id + element id) |
| D2 | Inputs are **hash-pinned**: every raw file's SHA-256 is recorded; a rebuild must reproduce identical hashes | CI compares hashes |
| D3 | Solver input uses an **allow-list schema** (concept, value, unit, decimals, period, dimensions, filing metadata, linkbase arcs as published). Any other field fails ingestion | Schema validator in CI (not a deny-list) |
| D4 | Linkbase arcs are **as published** (extension elements keep their real arcs). Hard cases are created by *hiding* real arcs, never by omitting them by author choice | Arcs generated by the parser only |
| D5 | Sampling is **random or rule-based and recorded**, never author-picked | Sampling script + seed committed before data is parsed |

### 4.2 Gold labels

| ID | Rule | Enforcement |
|---|---|---|
| G1 | Gold comes from **sources the solver never sees as input**, and the producing code does not import solver or KB modules | Import-graph check |
| G2 | **Three gold sources**, each with its own metric: (a) *reported statement totals* from the filing (self-verifying via identities); (b) **hidden published calc arcs**: for extension/standard elements that have real calc arcs, withhold the arcs from the solver and score parent + weight recovery (free, large, independent gold); (c) **human labels** on a stratified sample, double-annotated, with adjudicated disagreements and reported inter-annotator agreement | Gold manifest records source type per label |
| G3 | Gold is **written before the solver is run** on that data, and committed (hash) | Commit-order check |
| G4 | **Abstention is a first-class label.** "Should abstain" is decided by an annotator rule, not by looking at solver output | Labeling guide + audit sample |

### 4.3 Splits and holdout

| ID | Rule | Enforcement |
|---|---|---|
| H1 | **Three-way split**: Seed (learn), Dev (tune), **Sealed holdout** (score once). Splits by *firm*, and also by *time* (e.g. seed ≤ FY2022, holdout FY2024–25), and stratified by size class and SIC division | Split manifest committed with hash |
| H2 | The sealed holdout is **drawn at random** from EDGAR (e.g. by hash of accession number), with a minimum size (see §6) | Sampling script |
| H3 | **One-shot access**: holdout scoring is logged; after a holdout run, any change to lexicon/rules/code **burns** that holdout. The next version gets a fresh draw | Access log; CI blocks re-use of a burned holdout ID |
| H4 | **Pre-registration**: metrics, thresholds, and the version being tested are committed *before* the holdout is scored | Git tag required for a holdout run |
| H5 | No filing from a firm in Seed may appear in Holdout (including other fiscal years) unless the test is explicitly labeled "same-firm, later year" and reported separately | Split manifest check |

### 4.4 Knowledge base and lexicon

| ID | Rule | Enforcement |
|---|---|---|
| K1 | The initial lexicon is built **only from the taxonomy** (element names, labels, definitions, taxonomy calc/pres trees), never from any test filing | Provenance field on every lexicon entry; entries sourced from a test filing fail CI |
| K2 | After K1, **all learning comes from Seed evidence** with provenance (§15.3 of the spec). Evidence is append-only, with scope and trust level | Evidence store is the only write path |
| K3 | A KB version is a **snapshot with hash** covering lexicon + rules + evidence + parser code hash. Holdout scoring is tied to that hash | `kb.freeze()` hashes all four, not just rules |
| K4 | Inferred evidence cannot promote to broader scope without non-inferred support (§15.4) | Promotion check |
| K5 | **No firm names, tickers, or qname literals** in solver code or goal specs. Firm quirks exist only as scoped evidence | Lint (ticker list, `us-gaap:`/extension literals outside fixtures) |

### 4.5 Metrics

| ID | Rule | Enforcement |
|---|---|---|
| M1 | Report **risk–coverage**: precision on answered, coverage (answered / all), abstention rate, and **abstention correctness** separately. Abstained facts stay in the denominator of coverage | Metric code reviewed against definitions in §9 |
| M2 | Report by stratum: standard vs extension; primary statement vs notes; size; SIC division; year; plus **extension-only** and **dimensional-only** rows | Report template |
| M3 | Every headline number carries a **95% confidence interval** (Wilson for proportions; bootstrap by firm for goal-level metrics) and the **n** | Report template fails without CIs |
| M4 | **Placement accuracy** = (right parent) × (right decomposition) × (right weight), as in spec §C13.4, reported alongside coverage | Metric implemented |
| M5 | Compare against **independent baselines**: (a) published mapping table (e.g. an open-source standardization map), (b) token-match baseline, (c) majority-class | Baselines implemented by someone/something other than the solver author |
| M6 | Ablations must show **the same holdout, same gold**; no per-ablation re-tuning | Single script |

### 4.6 Robustness and leakage tests (must pass before any claim)

| ID | Test | Expectation |
|---|---|---|
| T1 | **Hidden-arc test**: remove all calc arcs for extension elements | Report placement accuracy with and without arcs; the gap is the true contribution of structure |
| T2 | **Rename perturbation**: replace element names with synonyms/typos that keep the structure | Accuracy degrades gracefully; report the drop |
| T3 | **Label shuffle (negative control)**: shuffle gold labels | Score collapses to chance; if not, the metric is broken |
| T4 | **Canary tags**: insert fake elements with nonsense names and known structural position | Solver must abstain or place by structure only, never invent a kernel |
| T5 | **Leakage scan**: grep solver code for any identifier that appears in gold files but not in seed data | Zero hits |
| T6 | **Independent re-implementation** of the core classifier by a separate code path with no shared imports; only then use the term "independent" | Import-graph check |
| T7 | **Failure injection**: duplicate facts, `nil` facts, wrong scale, restated values | Solver emits explicit diagnostics, never silent wrong values |

## 5. Phased plan

| Phase | Goal | Deliverables | Exit gate |
|---|---|---|---|
| **P0 — Triage (1–2 days)** | Stop overclaiming | Relabel v3 as *development fixtures*; withdraw "100% held-out" language; replace deny-list with allow-list schema; fix metric definitions (M1) | README states what v3 does and does not show |
| **P1 — Real ingestion** | Remove S1, S4 | Parser for iXBRL/XBRL instance + `_cal/_pre/_def/_lab` linkbases; corpus of **≥ 150 filings** to start, hash-pinned (D1, D2, D4); stored in SQLite | Round-trip: every parsed fact traces to file/context/element; identities hold on ≥ 95% of statements |
| **P2 — Independent gold** | Remove S2, S3 | Gold pipeline per §4.2 (G1–G4): reported totals, hidden published arcs, double-annotated human sample (≥ 300 facts, κ reported) | Gold manifest committed; solver has never run on it |
| **P3 — Splits** | Remove S6 | Seed/Dev/Sealed split by firm, time, stratum (H1–H5); pre-registered metrics | Split manifest + pre-registration tag |
| **P4 — Learn, don't author** | Remove S5 | Lexicon v0 from taxonomy only (K1); evidence KB built from Seed (K2); hash covers lexicon+rules+evidence+code (K3); lint K5 | `kb.freeze()` hash reproducible; lint green |
| **P5 — Score once** | Honest numbers | One holdout run (H3), full risk–coverage and strata (M1–M4), baselines (M5) | Report with CIs; holdout burned |
| **P6 — Stress** | Remove S8–S11 | T1–T7; independent second implementation | Degradation curves documented; failures triaged into evidence |
| **P7 — Iterate** | Improve with discipline | Fix failures only through evidence/KB changes; draw a **fresh holdout** each time | Each version carries its own sealed-holdout report |

## 6. Sample sizes and initial gates (proposals to tune)

Use these to avoid reading noise as signal. With zero errors, the 95% upper bound on the error rate is about 3/n; for 5% resolution you need n ≈ 60 per stratum, for 1% about 300.

| Metric | Minimum n per reported stratum | Initial gate (95% lower bound) |
|---|---|---|
| T1 anchors (assets, equity, retained earnings, cash-flow totals; spec §C11) | ≥ 100 filings | Precision ≥ 98%; coverage ≥ 90% |
| T2 derived anchors | ≥ 60 filings where the line is absent | Derived value exact within rounding in ≥ 95% |
| Extension placement (parent × decomposition × weight) | ≥ 300 extension facts from ≥ 60 firms | Placement accuracy ≥ 80%; abstention correctness ≥ 90% |
| Dimensional roll-up (slices) | ≥ 100 aggregates | Correct basis (reported / derived / conflict) ≥ 90% |
| Silent wrong answers (wrong value, no diagnostic) | all | **0** observed in holdout, upper bound reported |

Thresholds are starting points; the point is that they are fixed in advance (H4).

## 7. Immediate next actions

1. Add a README banner to v3: "development fixtures; results are in-sample".
2. Write the ingestion parser (P1) and run it on a 20-filing pilot to confirm identities hold on real instances.
3. Prototype the **hidden-arc experiment (T1/G2b)** on that pilot: it gives independent gold for extension placement almost for free and directly tests the thesis in spec §C13.
4. Draft the labeling guide for human gold (G2c, G4), including the abstention criteria.
5. Commit the split manifest and pre-registration template before any further engine changes.

## 8. Open decisions

1. Which parsing stack (e.g. an existing XBRL library vs. a minimal in-house parser)? A tested library reduces S1-type risk.
2. Who labels the human sample, and how are disagreements adjudicated?
3. Do we keep both engines (in-memory + SQLite), or keep one and invest in the independent re-implementation (T6)?
4. Is time-based splitting feasible given taxonomy-year changes (alias maps needed, spec E-NORM-1)?