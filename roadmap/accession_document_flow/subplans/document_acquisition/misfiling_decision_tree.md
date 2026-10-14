# Architecture & Implementation Plan: S10 Role-Assessment Contract

## Goal Description

This D0 document records the separate S9 acquisition-suspicion and S10 role-assessment
contracts. Current S6 projections emit no family-trigger pins, and the S9 runner refuses
lazy-index recovery without them. The retained `exact_form_with_lazy_index` field does
not currently authorize an index request. S10 diagnoses the already-selected body against
pinned S6 intent; diagnostics and operation outputs never feed back into acquisition.
The contracts do not share scan results or dataclasses.

**Runtime status:** This is a research/design record, not evidence that an S10 evaluator
is enabled. The former engine evaluator package and `EvaluatorDecision` action SPI were
removed; `REFETCH_SUB_DOC` and `SKIP_HARD_STUB` are not runtime actions. External EX-13
research evidence may remain as provenance, but it does not authorize a refetch or
classify a target at runtime.

**Tracked implementation status (2026-10-13):** Authority-qualified exhibit registries
and candidate packs exist as domain data, but no runtime S10 profile consumes them. The
S9/S10 fixture review generator/comparator/analyzer is wired for the limited raw/TEXT
processing slice. D6a is partially wired, not complete: reproducible review artifacts
exist, but evaluator identity, human labels, and role-assessment results are absent. D5
ownership reconciliation, D6b holdout, and D7 private evaluator integration remain
incomplete.

Initial form scope is 10-K, 10-Q, and 8-K under Item 601. Form 20-F remains a separate
source authority but is disabled in the initial S10 scope.

---

## Proposed S10 Assessment Contract

To prevent a combinatorial explosion of form-specific diagnostic strings, the assessment model cleanly separates:
1. **The Diagnostic Category (`diagnostic_code`):** A small, closed, stable enumeration.
2. **The Specific Types (`expected_type`, `observed_type`):** Dynamic form/exhibit identifier strings.
3. **The Human/Audit Details (`diagnostic_detail`):** A formatted explanation of the discrepancy.

### Canonical Diagnostic Codes:
- `None`: When disposition is `consistent` or `insufficient_evidence`.
- `"form_mismatch"`: When another registered primary report is observed, but `observed_type != expected_type` (e.g. expected `10-K`, but observed `10-Q` or `8-K` in the initial profile set). Scales to additional profiles without adding new codes.
- `"suspected_misfiled_exhibit"`: When `expected_role == "primary"`, but the body is an exhibit.
- `"suspected_misfiled_primary"`: When `expected_role == "exhibit"`, but the body is a primary report.

```python
# ExhibitIdentity = (authority_id, code)
# content_family and pack_id are separate concepts.

@dataclass(frozen=True, slots=True)
class DocumentRoleAssessment:
    schema_version: int
    evaluator_version: str
    taxonomy_version: str
    expected_role: str  # pinned S6 intent
    expected_type: str  # pinned S6 target_type; not body truth
    filing_form: str  # pinned S6 form
    expected_identity: PrimaryFormIdentity | ExhibitIdentity | ScheduleIdentity | None
    observed_kind: Literal["primary_report", "exhibit", "schedule", "structured_data", "paper_stub", "unknown"]
    observed_identity: PrimaryFormIdentity | ExhibitIdentity | ScheduleIdentity | None
    disposition: Literal["consistent", "possible_role_mismatch", "insufficient_evidence"]
    diagnostic_code: str | None  # "form_mismatch", "suspected_misfiled_exhibit", etc.
    diagnostic_detail: str | None
    supporting_evidence: tuple[MatchedSignal, ...]
    contradicting_evidence: tuple[MatchedSignal, ...]
    matched_evidence_tier: str | None
    confidence_band: str | None  # ordinal, never a probability
    evaluator_quality: str
    profile_id: str
    profile_version: str
    pack_id: str | None
    pack_version: str | None
```

---

## 3. Multi-Form Recognition as Registered Profiles

This decision tree should handle **multiple forms through one form-agnostic evaluator**,
not a set of form-specific branches. Primary recognition is
data-driven: each supported primary form contributes a source-backed profile. Exhibit
identity is resolved separately through filing context and authority-qualified codes.
Mismatch diagnostics compare the expected form with a registered observed primary
profile. Adding a form adds profile data and tests, not a decision-tree branch or
diagnostic code.

The repository already owns form taxonomies in
[`edgar_sec/domain/forms/families/`](../../../../edgar_sec/domain/forms/families/README.md).
Reuse those definitions as profile data instead of duplicating their item vocabulary.
Primary-profile selection may use retained form-family taxonomy data, but no active
evaluator registry exists. Assessment would require an explicit separately implemented
profile; do not infer activation from plugin-family membership.

- The annual taxonomy provides 10-K and 20-F item sets. Form 10-K is in the initial
  primary scope; Form 20-F is a separate exhibit-code authority until primary assessment
  is explicitly added to S10 scope and backed by fixtures.
- The quarterly taxonomy provides the 10-Q item set.
- The current taxonomy covers 8-K and 6-K. Form 8-K is in the initial primary scope.
  Form 6-K has local form evidence, but its instructions define a cover, variable
  issuer-furnished report/document, and signature page (`uploads/6-k.md:45-80`). It
  remains unregistered until its selected-body semantics and fixtures are reviewed.
- Other forms, including Form 4, remain out of scope unless a profile is explicitly
  justified and reviewed.

### Scope audit of existing form references

| Current reference group | What it represents | Design treatment |
|---|---|---|
| Goal and primary-profile scope | 10-K, 10-Q, and 8-K are the initial primary roles in the existing S10 assessment | Keep primary recognition form-agnostic and profile-driven; do not expand S10's primary scope in this plan. |
| Item 601 index placement | 10-K, 10-Q, and 8-K use Item 601 exhibit sections; Form 20-F has separate exhibit instructions | Keep source-specific spans and numbering in profiles; never apply Item 601 rules to Form 20-F. |
| Item 601 applicability table | S-1, S-3, SF-1, SF-3, S-4, S-8, S-11, F-1, F-3, F-4, Form 10, 8-K, 10-D, 10-Q, 10-K, and ABS-EE | Preserve every source row, but do not auto-register these forms; current S10 runtime scope remains 10-K, 10-Q, and 8-K. |
| Diagnostic taxonomy and mismatch examples | Expected vs. observed primary form values | Keep generic; preserve the closed `form_mismatch` code and dynamic type IDs. |
| Existing form-family taxonomies | Form-specific Part/Item vocabulary | Reuse as profile data; do not put form checks into the exhibit-pack modules. |
| Existing plugin registry | Dedicated 10-K, 20-F, 10-Q, and 8-K plugins; generic fallback for 6-K and unknown forms | Reuse only as a lookup seam; plugin registration is not assessment activation. |
| Original flowchart and execution ladder | Literal alternatives for 10-K, 20-F, 10-Q, and 8-K | Replace with profile lookup and alternate-profile comparison; initial primary profiles remain 10-K, 10-Q, and 8-K. |
| Form 20-F | Local instructions establish a separate exhibit-code namespace; current S10 role-assessment scope does not include the form | Keep source-qualified coverage rows disabled; enable exhibit or primary assessment only after separately scoped and fixture-backed. |
| Form 6-K | Local instructions and current-family evidence exist; form content includes a wrapper around issuer-furnished material | Do not activate from family membership. Defer until target/body selection semantics and fixtures support a profile. |
| Form 40-F | Mentioned as a Form 6-K cover-page annual-report election; no 40-F instructions or profile are in scope | No implicit primary or exhibit assessment; require its own source review and explicit profile. |
| Item 601 vs. Form 20-F exhibit-number examples | Proven authority-local code collision (e.g. EX-1 vs. exhibit 1) | Keep only as source-qualified coverage/alias data; no 20-F-specific branch in the evaluator. |
| Form 4 | Outside the current S10 form scope | No registered profile means no evaluation and no assessment. |

Thus the design scope is a form-agnostic role evaluator with declarative, independently
registered primary-recognition and exhibit-applicability profiles. The initial
primary-report profile set follows the current S10 scope: 10-K, 10-Q, and 8-K. Item 601
is the initial exhibit authority for those in-scope forms where its table establishes
applicability. Form 20-F coverage rows preserve its distinct code namespace but remain disabled for S10 assessment;
its existence does not activate primary or exhibit classification. Forms 6-K, 40-F, and
other unregistered forms likewise receive no assessment. Profile expansion requires
source-backed rules, selected-body fixtures, and an explicit scope decision. Exhibit
content packs remain form-independent unless local sources prove an applicability rule
or a real authority/code collision.

---

## 4. Invariant: Table of Contents is Sufficient, Never Necessary

> [!IMPORTANT]
> **No mandatory structural signal:** The evaluator must tolerate a body without a detected Table of Contents or exhibit-index span. It cannot assume every supported form or acquired representation exposes one.

Therefore, the decision tree enforces a strict asymmetric rule:
- **TOC/index spans are corroborating evidence:** If a profile-recognized contents or exhibit-index span is detected, it can shield exhibit-like references attributable to its rows. It is not a global veto against an unrelated standalone exhibit title elsewhere in the body.
- **TOC absence is never a rejection gate:** If no such span is detected, evaluate:
  1. Statutory title header (e.g. `"ANNUAL REPORT PURSUANT TO SECTION 13..."`).
  2. Standalone form designator line for a registered primary profile.
  3. Commission header (`"UNITED STATES SECURITIES AND EXCHANGE COMMISSION"`).
  4. In-body headings declared by the registered primary profile.

These designators and headings are examples from currently available profiles, not the
closed set of forms supported by the generic evaluator. A contents span is interpreted through
the selected profile and protects only matches attributable to that primary document.

---

## 5. End-to-End Decision Tree Architecture

The decision tree runs after S9 selects and stages a body. It uses bounded text, the
pinned filing/target context, and available structural spans; profile and pack rules set
their own narrower evidence windows:

```mermaid
flowchart TD
    START["S9-selected staged body + pinned target + normalized text"] --> BYPASS{"Supported route and non-empty text?"}
    BYPASS -->|No| NOEVAL["No content-role assessment"]
    BYPASS -->|Yes| PROFILE["Resolve registered profile and source authority"]
    PROFILE -->|No profile| NOEVAL
    PROFILE -->|Profile found| SHIELD["Mark TOC / exhibit-index spans as primary evidence"]
    SHIELD --> EXTRACT["Bounded opening probe<br/>form designator / exhibit code / schedule / standalone title"]

    EXTRACT --> EXPECTED{"Expected role?"}
    EXPECTED -->|primary| PRIMARY["Score expected primary profile cues<br/>using its taxonomy and available spans"]
    PRIMARY -->|consistent| ACCEPT["observed primary type = expected type<br/>disposition = consistent"]
    PRIMARY -->|not matched| ALTERNATE["Indexed lookup among registered primary profiles<br/>score selected alternatives only"]
    ALTERNATE -->|alternative meets threshold| MISMATCH["observed primary type != expected type<br/>diagnostic_code = form_mismatch"]
    ALTERNATE -->|no alternative| EXHIBIT
    EXPECTED -->|exhibit| EXHIBIT["Source-qualified exhibit lookup<br/>direct designator, then pack-specific title tiers"]
    EXHIBIT -->|confidence threshold met| EXMATCH["observed exhibit identity<br/>diagnostic_code = suspected_misfiled_exhibit"]
    EXHIBIT -->|no qualifying evidence| SCHEDULE
    SCHEDULE["Schedule profile / designator evidence"] -->|matched| SCHED_MATCH["observed schedule type<br/>diagnostic_code = suspected_misfiled_schedule"]
    SCHEDULE -->|no qualifying evidence| INSUFF["observed_kind = unknown<br/>disposition = insufficient_evidence"]
```

### Boundary with S9 lazy-index selection

If a versioned family trigger is later pinned, S9's lazy-index screen is a network-request
gate; S10's prose classifier is a diagnostic. No current plan enables that screen.
Their evidence thresholds are independent. A weak but plausible S9 suspicion may justify
spending one index request even when it would be insufficient for S10 to report a role
mismatch. In an idealized set of `N` catalog-direct primary candidates where `p` are known
inversions requiring recovery, the screen passes `N - p` without an index request and
requests the index for `p`. Real screens can have false positives or false negatives;
the cost/recall tradeoff is measured separately and the screen's “pass” is not a type
assertion.

Only a unique SEC-index row matching the pinned filing form can authorize a changed
physical-slot assignment. A local suspicion signal can request that lookup but cannot
identify the selected document by itself. Ambiguous or missing index evidence remains an
S9 selection outcome; S10 does not repair it. The retained S9 contract describes a future
screen that decides whether to spend a request, while only index/bundle metadata creates a
`slot_types` fact ([acquisition decision tree](decision_tree.md#catalog-direct-primary-selectors-and-lazy-recovery)).

S10 evaluates the already selected body for an advisory content-role assessment. A
source-backed profile reports only what its diagnostic evidence supports; that inferred
`observed_identity` is not an SEC-index assertion. S10 must not trigger an index request,
authorize/rewrite a selected sequence, change a target or route, or serve as input to the
S9 lazy-index screen. Conversely, a completed S9 selection does not make S10's body
classification authoritative or guarantee that the inferred identity matches an index
row.

### Reuse audit: fast cues and one-scan candidates

Audit these owners before adding new form-title or structural regexes:

| Need | Existing owner and behavior | Design disposition |
|---|---|---|
| TOC candidates | [`toc/finder.py`](../../../../edgar_sec/engine/forms/cover/toc/finder.py) exposes `find_toc_span(text, ..., derived_taxonomy=...) -> TocSpan \| None`; it returns one span with offsets and evidence. [`boundary/detector.py`](../../../../edgar_sec/engine/forms/cover/boundary/detector.py) returns one cover interval and copies evidence strings, not the `TocSpan`. | D0 should split profile-independent candidate discovery from profile-specific scoring, returning all candidate spans from one scan. The normalizer can choose one boundary; the evaluator can compare alternatives in memory. Do not run a whole-text finder once per profile. |
| Normalizer TOC scans | [`normalize.py`](../../../../edgar_sec/engine/forms/normalize.py) detects a TOC for cover boundary, then scans again after text normalization with derived taxonomy. The text frames and inputs differ. | Do not delete either scan by changing only the signature. D0 must map source/normalized coordinates and identify which final spans `NormalizationResult` can safely retain for S10. |
| Cover checkmarks | `extract_cover_candidates(text, boundary, *, family, table_geometries=())` emits labeled `CheckboxCandidate`s, mark states, and character spans; `infer_cover_checkmarks(...)` resolves them. Normalization uses the result for rewriting, then drops it; rewrites/reflow can move offsets. | Reuse resolved checked-state evidence and source spans if preserved by the owner result. If multiple candidate cover schemas are needed, expand extraction to scan once and resolve the candidates in memory. A phrase without a reliably selected mark is only weak suspicion; do not rescan rewritten text. |
| Form-title data | Annual, quarterly, and current title tuples exist in `domain/forms/families/*/evidence.py`, but production code does not consume them. `domain/forms/common/vocabulary.py` recognizes broad `FORM`/`SCHEDULE` tokens, not a canonical mismatch. | Reuse reviewed vocabulary as data, not as an existing classifier. `foundation/text/automaton.py` and `foundation/text/evidence.py` can share lexical scans; their positions are token-based and need explicit mapping to source spans. |
| Historical evaluator notes | External EX-13 delegation/stub evidence and `body_start.find_body_start` candidate behavior are research context, not an active evaluator SPI. | Keep any EX-13 source material as external evidence only; do not reintroduce evaluator-driven actions or claim runtime classification. |

Cheap competing-form cues can precede TOC/profile scoring. Local templates expose an
annual-versus-transition choice on Form 10-K (`uploads/10-k.md:152-162`), a quarterly
report choice on Form 10-Q (`uploads/10-q.md:99-103`), and a Form 20-F/40-F annual-report
election on the Form 6-K cover (`uploads/6-k.md:26-29`). The latter is a 6-K signal, not
a 10-K checkbox. If a body expected to be 10-K contains a reliably selected competing
cover choice, it may raise S9 suspicion before TOC analysis, but it does not establish
`observed_identity`. A phrase alone, an unchecked option, or an offset from a rewritten
text frame must not be promoted to a selected-form fact.

The D0 signature decision should be an actual extraction/result seam, not just a wider
annotation on `find_toc_span`: discover candidate TOC boundaries once, retain their
offsets/evidence, and score them against each registered taxonomy without rescanning the
body. Likewise, let cover candidate extraction accept the registered choice vocabulary
needed for suspicion, then return mark state and source span once. Keep the normalizer's
pre-rewrite and post-rewrite scans distinct until equivalence across their text frames is
proven; source offsets may require a rewrite map before S10 can reuse them.

The legacy date/name inversion predicate and resolver are retired with
`document_storage`; they are not current S9 rules. Do not use them as a lazy-index signal.
Review-run and fixture evidence establishes accession-prefixed direct paths for positive
numbered children, including `0001`; that filename alone is not a placeholder signal.
Exact primary `0000.txt`/`.htm` remain the placeholder cases and require pinned bundle
and observed-sequence evidence. The catalog-direct selector field remains in the plan
contract, but current projections have no family-trigger pins, so its response screen
does not run. Historical layout heuristics do not replace observed locator evidence.

 One-pass is a semantic contract, not just a wider return annotation: discover structural
and lexical candidates for a given text frame once, retain stable source spans, and score
those candidates against multiple profiles without rescanning the full text. TOC,
checkmark, and normalization passes have distinct scopes today, so D0 must choose the
result owner and coordinate mapping before promising fewer scans. S9 consumes low-threshold
suspicion facts only; S10 applies its independent diagnostic threshold to the selected
body.

### Coordinate Frame Contract (D0 frozen)
- `EvidenceSpan(start_char, end_char)` is strictly indexed against the **final normalized
  text frame** (`NormalizationResult.text`).
- Cues resolved prior to destructive text rewrites (specifically, cover checkmarks) are
  preserved as **semantic facts** on `NormalizationResult.cover_checkmarks` rather than
  attempting backwards character offset mapping.
- Multi-candidate TOC discovery is decoupled from profile-specific scoring; the normalizer
  owns the cover boundary and TOC span while the evaluator may compare candidates in memory.

---

## 6. Execution Steps: Scalable Classification Ladder

### Step 1: Designator & Document Class Extraction
- Use registered profile designators plus shared exhibit/schedule patterns to extract
  normalized candidate identities from the bounded text.
- Preserve the observed prefix, raw code, source authority, and line position; do not
  reduce a source-qualified exhibit number to an integer-only key.
- Compile alternatives with `build_alternation`; the evaluator does not enumerate form
  names in branching logic.

### Step 2: Primary-Profile Verification
1. Resolve the expected type to its registered primary profile.
2. If a TOC span exists, score only its rows against that profile's taxonomy.
3. Without a TOC, score the profile's own title, designator, and structural anchors from
   a bounded view. TOC omission never rejects a candidate by itself.
4. On a primary match, short-circuit exhibit-pack evaluation. When the expected profile
   fails, use indexed profile cues to select alternate primary candidates; compare only
   those candidates, then report a generic `form_mismatch` if an alternate meets its
   evidence threshold.

### Step 3: Generic Form Mismatch Diagnosis
- If primary checks fail against `expected_type`:
  - If the body matches another registered primary profile:
    - `observed_kind = "primary_report"`
    - `observed_type = matched_form`
    - `disposition = "possible_role_mismatch"`
    - `diagnostic_code = "form_mismatch"`
    - `diagnostic_detail = f"observed primary form '{matched_form}' conflicts with expected form '{expected_type}'"`

### Step 4: Misfiled Exhibit & Schedule Resolution
- If primary checks fail completely:
  - Check a standalone exhibit designator, then the applicable pack's standalone title
    rule within its own opening `N`-line window and required tier/confidence threshold.
  - Use the selected profile's exhibit-index/TOC spans as shields; do not globally veto
    an exhibit match merely because a form-family label or any TOC signal was seen.
  - If no exhibit candidate qualifies, check registered schedule evidence; otherwise
    abstain as insufficient.

---

## 7. Proposed Changes

This document is a design record, not evidence that an evaluator is active. Source-backed
profile and pack declarations now exist in `domain/forms/exhibits/`, and the limited
S9/S10 fixture review path is wired, but no body evaluator consumes those declarations.
Offline evaluator work may proceed in diagnostic-only mode before corpus completion.
Holdout evidence and recorded acceptance gate family activation; S10 findings remain
read-only and cannot change S6 or S9 behavior. M9 publication remains separately gated.

### Domain contracts and visible coverage

Keep filing-form assessment separate from exhibit identity and from evidence text:

```text
# Historical proposed domain contract; not current runtime.
edgar_sec/domain/forms/
  common/exhibits.py                  shared immutable assessment/pack contracts
  exhibits/
    README.md
    coverage.py                       unified source-qualified code ledger, including gaps
    registry.py                       authority + code -> content pack, indexed lookup
    profiles.py                       declarative applicability and tiered policies
    packs/
      README.md
      ex13.py, ex21.py, ...            code-named packs where identity is unambiguous
      ex1_item601.py                   collision-qualified pack when meanings diverge
      ex1_form20f.py                   distinct pack only when the clash needs one
edgar_sec/engine/forms/plugins/
  exhibit_selection.py               retained bounded header probe only
  # The former evaluators/ package and role-decision modules are retired.
```

Keep the engine and pack contract form-agnostic. `ExhibitIdentity` is exactly the
source-qualified pair (`authority_id`, `code`); `content_family` and `pack_id` are
separate concepts. A subitem such as Item 601 31(i) is represented in the canonical code,
not as another identity dimension.
Applicability profiles are declarative data loaded by a generic evaluator; it contains no
`if form == ...` branches or form-named evaluator modules. A profile may state form
conditions only when local source material establishes them. Unregistered forms receive
no exhibit evaluation. Use names such as `ex13.py` when the code identifies one pack in
the registry; qualify a module when local sources prove the same number denotes different
content in another namespace. Item 601 EX-1
(underwriting agreement) versus Form 20-F exhibit 1 (organizational documents) is one
such proven collision; the Form 20-F #13 / Item 601 EX-13 meanings also differ. This is
evidence for authority-qualified identity, not a Form-20-F-specific engine. If two
source-qualified identities share a visible-content rule, they may reference one shared
pack only after the duplicate audit establishes that reuse is safe. Dotted subtypes remain
separate pack IDs where required, e.g. Item 601 3(i)/3(ii) and 31(i)/(ii). Split a pack
into a nested package only if it grows beyond a cohesive module; do not consolidate all
vocabularies into one `evidence_packs.py`.

Module and directory names in this plan are illustrative, not copied from research-note
snippets. Select final names after checking package ownership, test mirroring, README
requirements, and `AGENTS.md` conventions.

`coverage.py` is the single source-of-truth ledger across authorities and form scopes. It
must distinguish statutory recognition from actual evaluator readiness. Proposed statuses:

- `reserved`: the cited authority-local number is reserved; no classifier pack.
- `unsupported`: a statutory item is known, but available evidence does not support a
  safe body evaluator or it belongs to another representation pipeline.
- `candidate`: local sources motivate a candidate pack; this is not validated coverage.
- `partial`: only named subtype(s) are candidates; the broader exhibit code remains
  uncovered.

Pack maturity is separate from coverage status. Pack `evaluator_quality` progresses
through `proposed`, `source_supported`, `fixture_reviewed`, `shadow_reviewed`, and
`holdout_evaluated`; the latter records evidence, not permission to change S6 targets or
classify authoritatively. Each coverage row records `authority_id`, an exact
authority-local code (including any subitem), aliases (including EDGAR spellings only
when verified locally), source status, proposed module/pack ID (nullable), coverage
status, source-backed applicability conditions, supported representation, and a
repeatable `source_refs` collection of path/section citations. A row may cite multiple
official documents and relevant research notes; the registry must not assume a fixed
number or name of Markdown inputs. Do not add a form name to a pack identity unless the source establishes
a form-specific rule or a real code collision; ordinary form applicability belongs in
profile data. Reserved, unsupported, broad, and structured-data items stay visible rather
than disappearing from the registry.

### Initial local-source coverage ledger

This inventory uses the official local text, applicable form instructions, current code,
and the evolving collection of relevant notes under `uploads/research/`. The present
notes include `exhibits-classification.md` and `exhibits-followup.md`; this list is not
closed. `EX-` labels are classification/EDGAR code conventions, not literal names used
throughout the CFR extract. Research-note snippets and regexes are untrusted proposals,
not ready-to-copy implementation. “Candidate” means proposed for source/fixture review,
not a claim that a rule works. The local Item 601 table lists form applicability at
`uploads/exhibits.md:77-134`; the local Form 20-F instructions have their own numbered
exhibit list (`uploads/20-f.md:1941-2064`). Form 6-K has distinct wrapper/body
instructions (`uploads/6-k.md:45-80`). The Item 601 table is not a universal form
classifier or a substitute for form-specific rules.

| Item 601 | Local-source scope | Proposed module / pack | Design coverage status |
|---|---|---|---|
| 1 | Underwriting agreements | `ex1_item601.py` | candidate; number clashes with a different source-defined exhibit 1 |
| 2 | Acquisition/reorganization and related plans | `ex2_item601.py` | candidate; distinguish transaction-plan types; number clashes |
| 3 | Articles and bylaws; handbook separates 3.1/3.2 | `ex3_item601.py` | partial; separate subtype packs; number clashes |
| 4 | Instruments defining security-holder rights | `ex4_item601.py` | partial; do not equate one indenture cue with full coverage; number clashes |
| 5 | Legality opinions | `ex5_item601.py` | candidate; tax opinions are a negative distinction; number clashes |
| 6 | Reserved | — | reserved |
| 7 | Accountant non-reliance correspondence | — | unsupported; no handbook family profile; number clashes |
| 8 | Tax opinions | `ex8_item601.py` | candidate; keep distinct from Item 5; number clashes |
| 9 | Voting-trust agreements | `ex9_item601.py` | candidate; number clashes |
| 10 | Material contracts | `ex10_item601.py` | partial; bounded subtypes only, not “any agreement”; number clashes |
| 11–12 | Reserved | — | reserved |
| 13 | Annual/quarterly shareholder reports | `ex13_item601.py` | candidate; distinguish annual/quarterly variants; number clashes |
| 14 | Code of ethics | `ex14_item601.py` | candidate; number clashes |
| 15 | Interim-financial-information letters | `ex15_item601.py` | candidate; number clashes |
| 16 | Change-in-accountant letters | `ex16_item601.py` | candidate; number clashes |
| 17 | Director-departure correspondence | `ex17_item601.py` | candidate; number clashes |
| 18 | Accounting-principles correspondence | `ex18.py` | candidate |
| 19 | Insider-trading policies | `ex19.py` | candidate |
| 20 | Other security-holder documents | — | unsupported until conditional scope has body evidence |
| 21 | Subsidiaries | `ex21.py` | candidate |
| 22 | Subsidiary guarantor/issuer/collateralizer lists | `ex22.py` | candidate |
| 23 | Expert/counsel consents | `ex23.py` | candidate |
| 24 | Power of attorney | `ex24.py` | candidate |
| 25 | Trustee eligibility statement | `ex25.py` | candidate |
| 26–30 | Reserved | — | reserved |
| 31 | Certifications, statutory subparagraphs (i)/(ii) | `ex31.py` | partial; separate ordinary and ABS packs |
| 32 | Section 1350 certifications | `ex32.py` | candidate |
| 33–36 | Servicing reports/statements and ABS shelf certification | `ex33.py`–`ex36.py` | candidate; separate by statutory type |
| 37–94 | Reserved | — | reserved |
| 95 | Mine-safety disclosures | `ex95.py` | candidate; applicability is conditional |
| 96 | Technical-report summary | `ex96.py` | candidate; specialist content, corpus needed |
| 97 | Compensation-recovery policy | `ex97.py` | candidate |
| 98 | De-SPAC reports/opinions/appraisals | `ex98.py` | candidate; conditional scope |
| 99 | Additional exhibits, including earnings statements | `ex99.py` | partial; only evidenced subtypes, never blanket EX-99 |
| 100 | Reserved | — | reserved |
| 101 | Interactive Data File | — | unsupported by prose evaluator; structured-data route |
| 102–103 | Asset Data File / asset-related document | — | unsupported pending representation-specific evidence |
| 104 | Cover Page Interactive Data File | — | unsupported by prose evaluator; structured-data route |
| 105 | Reserved | — | reserved |
| 106 | Static pool | — | unsupported; local handbook examples include index-page links rather than selected bodies |
| 107 | Filing fee table | `ex107.py` | candidate; structured/table cues and form scope need review |

The local Form 20-F text demonstrates a concrete numbering collision: its exhibit 1 is
organizational documents, while Item 601 EX-1 is an underwriting agreement. This
form-specific source is included to prove why the generic ledger needs authority-qualified
identities, not to make Form 20-F a special case in the evaluator. Do not interpret its
numbers as Item 601 EX codes. Keep them as rows in the unified, source-qualified ledger;
the suggested content-pack references below are only candidates for the later duplicate
audit, not form-specific implementation modules.

| Source code (`Form 20-F`) | Local-source scope | Candidate shared content pack | Design coverage status |
|---|---|---|---|
| 1 | Articles/association and bylaws | Organizational documents; compare with Item 601 EX-3 | partial; organizational subtypes |
| 2 | Rights of security holders and indentures | Security-holder instruments; compare with Item 601 EX-4 | partial; distinct instrument subtypes |
| 3 | Voting-trust agreements | Voting trusts; compare with Item 601 EX-9 | candidate |
| 4 | Material contracts | Material contracts; compare with Item 601 EX-10 | partial; do not treat every contract as a hit |
| 5 | Material foreign-patent list on request | — | unsupported; conditional list, no local body profile |
| 6–7 | Reserved | — | reserved |
| 8 | Subsidiaries | Subsidiary list; compare with Item 601 EX-21 | candidate |
| 9 | Financial-statement opinion for specified IPO context | — | unsupported pending a body-level evidence case |
| 10 | Regulation BTR blackout notices (annual report only) | — | unsupported pending a narrow local fixture/profile |
| 11 | Code of ethics and insider-trading policies | Separate ethics/policy subpacks; compare with Item 601 EX-14/19 | partial; keep subtypes distinct |
| 12 | Rule 13a-14(a)/15d-14(a) certifications | Ordinary certification; compare with Item 601 EX-31(i) | candidate |
| 13 | Section 1350 certifications | Section 1350 certification; compare with Item 601 EX-32 | candidate |
| 14 | Legal opinion required by Form 20-F Item 7.B | Legality opinion; compare with Item 601 EX-5 | candidate; distinguish from tax opinions |
| 15 | Additional exhibits / incorporated documents | — | unsupported until a narrow subtype has body evidence; open category is not a generic pack |
| 16 | Conditional mine-safety disclosure | Mine safety; compare with Item 601 EX-95 | candidate; condition and annual-report scope required |
| 17 | Subsidiary guarantors/issuers/collateral affiliates | Guarantor/affiliate lists; compare with Item 601 EX-22 | candidate |
| 18–96 | Reserved | — | reserved |
| 97 | Compensation recovery policy | Compensation recovery; compare with Item 601 EX-97 | candidate; annual report and listing condition required |
| 98–100 | Reserved | — | reserved |
| 101 | Interactive Data File | — | unsupported by prose evaluator; structured-data route |
| 102–103 | Reserved in the Form 20-F list | — | reserved; do not inherit Item 601 meanings |
| 104 | Cover Page Interactive Data File | — | unsupported by prose evaluator; structured-data route |

Source map: Item 601 general filing/index rules and exhibit list are in
`uploads/exhibits.md:9-38,77-134,136-696`; the local Form 20-F list is in
`uploads/20-f.md:1917-2064`. The research collection is open-ended; current examples include
`uploads/research/exhibits-classification.md:7-43,429-1492` and
`uploads/research/exhibits-followup.md:6-78,80-240`. Treat heuristic details in these
notes as hypotheses, not official rules or repository-ready patterns. No cited source
establishes validated packs. The local S10 assessment note records the lack of an exact
selected-body corpus, independent labels, and measured error rates
(`roadmap/accession_document_flow/subplans/S10_exhibit_assessment.md:11-32`).

### Pack and evaluator quality fields

Keep evaluator maturity separate from per-document confidence:

- Pack metadata and the copied assessment field `evaluator_quality`: `proposed`,
  `source_supported`, `fixture_reviewed`, `shadow_reviewed`, or `holdout_evaluated`.
  `source_supported`
  requires traceability to official local authority for legal identity/applicability;
  external research notes can nominate signals but cannot establish this status by
  themselves. It does not claim correct classification. This field states rule maturity,
  not the certainty of an individual result.
- Assessment fields `matched_evidence_tier` and `confidence_band`: tiers identify the
  strongest evidence path; the band is `insufficient`, `low`, `moderate`, or `high`,
  derived from declared pack thresholds and vetoes. It is ordinal, not a probability.

Every pack/result also pins `pack_id`, `pack_version`, `taxonomy_version`, evaluator
version, and matched signal IDs with bounded spans. An assessment copies the selected
pack's `evaluator_quality` so consumers can inspect rule maturity without a registry
lookup. `holdout_evaluated` requires issuer/accession-separated fixtures and reported
per-profile/per-pack confusion counts. Do not emit numeric confidence; the ordinal band
must not be interpreted as a calibrated probability or inferred from phrase count alone.

### Form-agnostic applicability and tiered dispatch

The evaluator is generic; applicability is declarative source data. Keep primary
recognition profiles separate from exhibit-authority profiles: the former recognize
10-K/10-Q/8-K primary bodies initially; the latter initially dispatch only Item 601
for those in-scope filings where the local applicability table supports it. Form 20-F coverage rows
preserve its distinct exhibit-code namespace but remain disabled for S10. An
`ExhibitAssessmentProfile` identifies the applicable source namespace, route/role
conditions, and an ordered candidate-tier graph. Profiles may be shared by filing forms
only when cited rules and evidence match. A role without an approved profile—including
Form 20-F, Form 6-K, Form 40-F, and Form 4 in the initial S10 scope—skips invocation and
produces no assessment (`None`), not `unknown` or a guessed result. Do not infer
applicability from a broad form family, plugin, or alias. A pinned S6 exhibit target
resolves by its source-qualified expected code; an unsupported code yields
`insufficient_evidence`, without altering the target.

For an eligible text/HTML body, dispatch in this order:

1. **Scope gate:** resolve the supplied canonical filing context and expected role.
   Primary-role checks require a registered primary profile; exhibit checks require an
   applicable exhibit-authority profile and source-qualified target identity. Skip when
   no profile applies, the route is unsupported, or the role is ineligible.
2. **Primary-document shields:** do not interpret a title or designator inside an available
   table-of-contents or exhibit-index span as a standalone exhibit header. Those spans
   remain primary-document evidence; their absence is never a rejection gate.
3. **Cheap direct-designator probe:** scan only a bounded opening-line view for a
   line-anchored `EXHIBIT <code>` or `EX-<code>` designator. The handbook's early-line
   window is a fixture hypothesis, not a legal rule; choose the operational bound from
   local fixtures. Normalize the captured code, then look it up using
   `(authority_id, code)`, never the number alone. A phrase in running prose is not a
   direct header. A match is evidence, not automatic acceptance.
4. **Pack-specific standalone-title probe:** only packs with a reviewed, discriminating
   title rule declare this evidence. Require the title to occupy a standalone heading
   line within that rule's first `N` lines; preserve the matched line number and signal
   ID. `N` is pack data selected from fixtures, not a global constant or legal threshold.
   A generic title such as “Agreement” is not discriminating. The pack declares its
   `matched_evidence_tier` and minimum `confidence_band`; a highly specific title may
   satisfy that threshold on its own only when the pack explicitly allows it and no veto
   or contradictory signal fires. Otherwise it only selects or supports candidate packs
   for later corroboration.
5. **Profile-local branch graph and fallback tiers:** when direct designation/title
   evidence is absent or below threshold, consult the selected profile. It branches on
   available, source-backed context and points to ordered candidate tiers. A profile-local
   cue index or compiled multi-pattern prefilter selects candidate pack IDs; score only
   those candidates. Do not loop over every exhibit pack or every profile for every
   document. Keep candidate ordering deterministic and short-circuit when a tier's
   declared decision rule is met.
6. **Abstain:** no supported pack hit, conflicting signals, or an unsupported code
   yields `insufficient_evidence`. Forms without an applicable profile are skipped
   before assessment.

Each profile owns its activation conditions, branches, and veto ordering as data; it
references shared code-owned packs rather than copying vocabulary. A profile may point
to filing-specific index/item cues or a source table's applicability conditions, but the
engine has no embedded form names. The exact candidates and tier weights remain
provisional until fixture review. Reuse the existing `LexicalEvidencePack` and
`score_unit()` only after routing has narrowed candidates; their lexical score is not the
branch graph and the `BowScore.confidence` field is not a calibrated content-role
probability. The Item 601 table and other form instructions describe filing requirements;
S10 only assesses the acquired body's declared role and never infers a missing target or
changes the plan from those requirements.

The cheap probe must be anchored to line start and the opening window, compile regex
alternations through `foundation.regex.builder` where applicable, and expose capture
spans. It should recognize standalone headers with or without a caption on that line,
while excluding ordinary sentences that merely mention an exhibit. It must not scan the
entire primary body for exhibit references.

### Engine and S10 seams

- The surviving `engine/forms/plugins/exhibit_selection.py` is a bounded header probe,
  not a role classifier, selected-pack evaluator, or acquisition action owner.
- The former `engine/forms/plugins/evaluators/content_role.py` and evaluator package
  are retired. This plan does not define current runtime behavior.
- `pipelines/document_acquisition/processing/worker.py` may attach the immutable assessment to
  `ProcessingResult` for eligible text/HTML only. It does not change target identity,
  route, profile, acquisition, retry, or normalization behavior. The fingerprint pins
  evaluator, profile, pack, and taxonomy versions when the shadow evaluator runs.
- S10 diagnostic output remains non-authoritative. Unknown, binary, XML/structured, and
  paper routes retain their existing route-specific handling and do not fall through to
  prose classification.

### Bounded evidence-review batches and duplicate audit

Before any packs are implemented, review candidate families in bounded, independent
batches. The source-inventory pass is not a pack-analysis assignment: no single reviewer
owns the entire Item 601 or Form 20-F set. Use this ten-batch plan for the later evidence
review; the Item 601 ranges are anchored in the exhibit table/descriptions
(`uploads/exhibits.md:77-134,138-696`), and the Form 20-F numbers in its own list
(`uploads/20-f.md:1959-2064`). The ledger remains the full inventory; these batches are
review assignments, not new taxonomy boundaries.

| Batch | Item 601 assignment | Form 20-F assignment | Why this is bounded |
|---|---|---|---|
| A — Transactions/contracts | 1, 2, 9, 10 | 3, 4 | Related agreement/planning evidence; Item 10 and Form 20-F 4 stay marked broad/partial. |
| B — Corporate instruments/opinions | 3, 4, 5, 8, 25 | 1, 2, 14 | Keep Item 5/8 opinion categories distinct; Form 20-F identity remains namespace-specific. |
| C — Professional correspondence | 7, 15, 16, 18, 23 | — | Bounded correspondence/consent set; Item 7 remains visible despite no handbook profile. |
| D — Governance/signature policies | 14, 17, 19, 24, 97 | 10, 11 | Small policy/governance set; preserve each type and applicable condition. |
| E — Holder-facing/entity material | 13, 20, 21, 22, 99 | 8, 15, 17 | Related high-level categories, but Item 20/99 and Form 20-F 15 do not become blanket packs. |
| F — Ordinary certifications | 31(i), 32 | 12, 13 | Separate Item 31(i) from ABS Item 31(ii); Form 20-F certification numbers are authority-local. |
| G — ABS reporting/certification | 31(ii), 33, 34, 35, 36 | — | Keep the ABS subtype family together for comparison while retaining independent pack IDs. |
| H — Conditional specialist reports | 95, 96, 98 | 16, 97 | Conditional/specialist evidence is isolated from ordinary corporate prose. |
| I — Reserved ranges | 6, 11–12, 26–30, 37–94, 100, 105 | 6–7, 18–96, 98–100, 102–103 | Verify reserved/gap records remain visible; no prose-pack heuristics. |
| J — Structured/table-oriented | 101–104, 106–107 | 5, 9, 101, 104 | Review representation and conditional/no-pack status; Item 107 remains a table-oriented candidate. |

Each assignment covers only its row and the corresponding local excerpts; use all
relevant official sources and any applicable notes under `uploads/research/`, recording
every path/section citation. Treat external suggested code, regex, module names, and
thresholds as hypotheses; verify and rewrite them for this repository rather than copying
literally. Item 10,
Item 99, Form 20-F 4, and Form 20-F 15 must not be bundled with many routine codes.
The long reserved ranges have their own low-heuristic batch rather than being mixed with
structured and table-oriented items. Do not assume same-numbered codes across authorities
are the same exhibit. Each reviewer returns for every assigned code: authority-local code, exact
source citations, candidate/partial/unsupported/reserved status, applicable form and
conditions, suggested module name, content-family proposal, bounded positive/negative
anchors, and possible duplicate/near-neighbor signals. No reviewer promotes pack quality
or resolves another batch's ownership conflicts.

After the bounded reviews and before approval of implementation, a separate integrator
reconciles the ledgers and runs a cross-pack ownership pass. Assemble the Form 20-F
number-to-pack-or-gap crosswalk from its bounded review rows and spot-check citations
against `uploads/20-f.md:1959-2064`; do not independently re-analyze the entire list.
Unresolved entries receive bounded follow-up assignments. Compare proposed codes,
aliases, headings, and lexical signals against current owners, including
`domain/taxonomy/schedules/statutory/exhibits.py`,
`domain/forms/families/annual/evidence.py` (`ANNUAL_TARGET_EXHIBITS` and existing annual
vocabulary), `domain/forms/common/vocabulary.py`, and the shared lexical machinery in
`foundation/text/evidence.py`. For each overlap, record `reuse`, `extend`, `new`, or
`exclude`, the current owner, and a short rationale. Identical strings are not
automatically duplicates when legal meaning differs; repeated generic terms should not
be copied into every exhibit pack. This audit is a distinct design gate, not a source
edit or an excuse to broaden the candidate set.

### Contract-first implementation task list

These milestones separate offline development from evidence-dependent activation. Missing
corpus evidence does not block fixture/review wiring or private shadow-mode iteration. No
milestone authorizes mutating S6 targets or S9 behavior; family activation and M9
publication retain their independent acceptance gates.

| Milestone | Deliverables / files | Depends on | Can run in parallel? | Exit condition | Status |
|---|---|---|---|---|---|
| **D0 — Reuse audit and contract freeze** | Map reusable TOC candidate/boundary, cover/checkmark, title-vocabulary, and legacy inversion APIs. Record which results/signatures must retain multiple spans, checked-choice evidence, and source offsets. Freeze a shared scan result consumed by separate S9 suspicion and S10 classification thresholds; then freeze request/result, pack/profile, coverage, and `source_refs` contracts in this design record. No active domain assessment contract is implemented. | Historical design milestone. | No; this is the contract gate. | Exact reuse/extension decisions, text-coordinate frames, and one input/output shape are documented; S9 cannot assert type and S10 cannot trigger a request. | Historical `[x]` |
| **D1 — Build domain scaffolding** | `domain/forms/exhibits/{coverage.py,registry.py,profiles.py}` and package READMEs. Add source rows, disabled candidate records, indexed lookup and profile schemas; no exhibit heuristics required. | D0. | Parallel with D2 and D3 after contract freeze. | Complete known-code ledger is representable; no inactive/unsupported row resolves to an active pack. | [x] |
| **D2 — Generic evaluator shell (retired)** | The former engine evaluator package and its action SPI are removed. The previous `engine/forms/plugins/evaluators/content_role.py` proposal and mirrored tests are not current paths; do not restore them. | Historical D0. | Retired. | No current S10 role evaluator is implied by this design record. | Retired (historical `[x]`) |
| **D3 — Review source evidence in bounded batches** | Analyzed `uploads/research/exhibits-classification.md`, `exhibits-followup.md`, `exhibit-collision.md` for Tier 1-3 anchors, tokens, veto signals, and form-generic constraints. | D0's row schema. | Yes; A–J are independent. No one reviewer owns the entire exhibit inventory. | Each Item 601 / source-specific code has a disposition; broad or uncertain types remain explicit gaps. | [x] |
| **D4 — Add reviewed pack modules incrementally** | Implemented 36 pack modules under `domain/forms/exhibits/packs/` (9 Tier 1, 15 Tier 2, 12 Tier 3) with `ExhibitPack` contracts, `mirror tests (`test_tier1_packs.py`, `test_tier2_packs.py`, `test_tier3_packs.py`), and registry wiring in `domain/forms/exhibits/registry.py`. Only store reviewed signals, tiers, and citations; do not add an unreviewed code to the active registry. | D0 and the corresponding D3 batch result; D1 package scaffolding. | Yes across disjoint batches/modules after D0. | Each active pack has a unique `pack_id`, source-qualified mapping, tests, and `evaluator_quality` no higher than evidence supports. | [x] |
| **D5 — Reconcile ownership and registry** | Registry lookup now fails closed unless coverage is candidate/partial and the selected pack has the same authority; disabled Form 20-F aliases and unsupported Item 601 codes do not resolve. Thirty-five mappings currently resolve. Full duplicate/owner audit against existing vocabulary modules remains pending. | D3 findings and D4 candidate modules. | No; reconciliation is a serial integration gate after parallel returns. | No unresolved duplicate signal has two owners; same-number/different-meaning identities remain distinct. | [~] |
| **D6a — Wire fixtures and review artifacts** | Review artifact v2 pins assessment/fingerprint when present. `review label` writes immutable sidecars linked to the exact selected body and processing artifact; two independent labels are required for consensus, and disagreement requires an append-only adjudication. `review analyze` summarizes labels. These plumbing tests are synthetic, not corpus evidence. | D1, M6 result boundary, and S9 local fixture reader. No live runner, holdout, or D5 audit is required for basic review artifacts. | Basic service/CLI path is complete; representative fixture evidence remains separate. | Review sidecars validate source, label scope, annotator/time, evaluator/taxonomy/profile/pack pins, and artifact digests. | [~] |
| **D6b — Evaluate labeled holdout** | `review holdout` validates a frozen issuer/time partition, rejects cross-partition exact body duplicates, and reports raw per-form/family TP/FP/TN/FN, ambiguity, abstention, and unresolved-label counts. Near-duplicate review is explicitly not performed. No representative selected-body corpus or accepted per-family results are available. | D6a, D7, reviewed labels, and sufficient representative cases. | Fixture curation can proceed by batch; threshold and holdout results are integrated centrally. | No numeric confidence claim; report counts and limitations. A family cannot be activated until its holdout is accepted and D5's duplicate/owner audit resolves its mapping. | [~] |
| **D7 — Integrate private S10 diagnostic shadow** | The opening-view evaluator is attached to `ProcessingResult` for eligible planned exhibits, with a separate diagnostic fingerprint and version-pinned review artifact output. It is read-only and does not change operation outcomes or target state. Current tests use injected test budgets and synthetic text; production budgets and fixture-backed assessments remain unavailable. | D0, M6 result boundary, and at least one source-cited D4 candidate pack/profile with an unambiguous identity. D6b is not required to wire non-authoritative shadow output. | Diagnostic wiring is complete; D6b and remaining pack review proceed independently. | Synthetic tests prove deterministic diagnostic transport and no operation-state mutation. Family activation still requires D6b and recorded acceptance. | [~] |

Dependency sketch:

```text
D0 contract freeze
 ├── D1 domain scaffolding ───────────────┐
 ├── D2 generic evaluator + tests ─────────┼── D5 registry integration ──┬── D6a fixture/review wiring ─┬── D6b holdout/acceptance
 └── D3 bounded source batches ─ D4 packs ─┘                              └── D7 private S10 shadow ───┘
```

#### Safe work before complete evidence research

The following work can proceed without waiting for a complete labeled corpus because its
contracts do not encode corpus-accuracy conclusions:

- `common/exhibits.py`: immutable request/result, identity, evidence-tier,
  confidence-band, evaluator-quality, profile, and assessment contracts. Research batches
  may add evidence records, but may not invent per-pack input/output shapes.
- `exhibits/coverage.py`: source inventory and statuses, including `unsupported`,
  `partial`, and reserved codes; an unreviewed source citation remains visibly pending.
- `exhibits/registry.py` and `profiles.py`: generic source-qualified lookup and empty or
  disabled profiles. Adding an entry does not activate it until its `CoverageStatus` and
  evidence gate permit it.
- The surviving exhibit-selection module remains a bounded probe only. A separate
  fixture-backed evaluator can be developed in diagnostic-only mode under the M8a/D6a
  boundary without granting authoritative behavior.
- Synthetic contract/routing tests. Later pack tests add real local fixtures without
  changing the public result shape.

Per-code pack modules may be scaffolded only after their identity and module name are
clear. An empty/proposed pack has no active registry entry and no title rule; do not
pretend a placeholder is coverage. Do not create modules for reserved or intentionally
unsupported codes. Full phrase research, the per-pack first-`N` title window, tier weights,
and minimum confidence band can be deferred independently once D0 fixes their fields.
That deferral does not block D1/D2 or other completed D3/D4 batches. `EX-10`, `EX-99`,
conditional items, and additional form profiles can remain partial/disabled while the
generic pipeline is implemented and tested. Expansion to currently unregistered forms
also does not block the initial profile set.

### Verification plan (for a later approved implementation)

1. **Coverage integrity:** mirrored tests assert every Item 601 and Form 20-F code
   reviewed from the local extracts has exactly one ledger row or reserved-range entry,
   every candidate module reference resolves, and every unsupported/reserved item has no
   active pack. Assert known same-number/different-meaning cases resolve by
   `authority_id`, never by integer code alone.
   The new exhibits package and its `packs/` subpackage need concise READMEs; add the
   package to `domain/forms/README.md`. Keep `__init__.py` files free of barrel
   re-exports.
2. **Pack tests:** compile each candidate regex/evidence pack; pin code aliases and
   subtypes; verify source-anchored positives, hard negatives, and ambiguous examples.
   A pack test must not promote maturity beyond its evidence.
 3. **Routing tests:** assert one direct registry lookup for an early header, no scans of
   inapplicable profiles, no iteration across the global pack registry, profile-specific
   ordering, and no assessment when an unregistered form such as Form 4 is supplied.
4. **Decision tests:** protect primary reports with Form TOCs and exhibit indexes,
   test no-TOC primary reports, test standalone exhibits with and without captions, and
   verify uncertain cases abstain. Keep diagnostic codes closed and parameterize code
   and detail.
5. **Fixture/review wiring:** the S7d acquisition/processing review CLI now generates,
   compares, and analyzes the limited captured S9/S10 cases offline. It does not export
   raw bodies to a user-selected path and does not evaluate exhibit or primary roles.
   Reproducible labeled evaluator review remains D6a follow-up work; it is not required
   for raw/TEXT processing or private evaluator development.
6. **Holdout gate:** partition reviewed labels by issuer/accession/time and report
   per-form/per-code false-positive and false-negative counts before claiming holdout
   evaluation or enabling a family. Synthetic cases and upload examples do not satisfy
   this gate.
7. **S10 integration:** verify assessment metadata is diagnostic-only and fingerprinted;
   verify normalization, S6 targets, and S9 work state are unchanged.
8. The former evaluator-test path has been removed. This historical gate is not runnable
   as written; any future approved runtime design must define its own mirrored tests.

The holdout gate does not block private offline wiring or diagnostic shadow tests. It
blocks only accuracy claims and family activation. Do not run `check.py` for this
planning-only change.
