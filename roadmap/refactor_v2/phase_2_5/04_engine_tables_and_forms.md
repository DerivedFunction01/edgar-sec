# Phase 2.5 — Sub-Plan 04: Engine Tables, Cover Checkmark Solver & Form Plugins

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Layer Focus:** Layer 3 (`engine/tables/`, `engine/forms/`)  
> **Source Grounding:** `.v1/defs/tables/`, `.v1/defs/sec_forms/cover/`, `.v1/defs/sec_forms/normalization/`, `.v1/defs/sec_forms/evaluators/`

---

## 1. Objectives & Architectural Role

Phase 2.5 contains two of the most algorithmically sophisticated components in the entire repository:
1. **Geometry-First Table Protection (`engine/tables/`)**: Identifies table structures across HTML grid tags and ASCII spacing, wrapping them in `<TABLE>...</TABLE>` sentinel markers so reflow never scrambles numbers or columns.
2. **Cover-Page Checkmark Constraint Solver (`engine/forms/cover/`)**: Uses quadratic penalty constraint satisfaction to resolve statutory checkboxes (WKSI, Shell Company, Accelerated Filer, 404(b), Restatement, Error Correction) under OCR noise, font-glyph mismatches, and contradictory markings.
3. **Delegation Evaluators (`engine/forms/evaluators/`)**: Detects filings that incorporate key disclosures by reference or delegate them to Exhibit 13, returning multi-scope actions (`REFETCH_SUB_DOC`).
4. **FormPlugin SPI (`engine/forms/plugins/`)**: Self-registering plugins providing form-specific normalization pipelines for 10-K, 10-Q, 8-K, 6-K, 20-F, Form 3/4/5, and Form 13F.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Invariants |
| :--- | ---: | :--- | :--- |
| `defs/tables/detector.py` | 380 | `engine/tables/detector.py` | Geometry-first table detection: column gaps, header alignments, numeric densities. |
| `defs/tables/grid.py` | 260 | `engine/tables/grid.py` | 2D cell grid estimation and tagged table delimiter insertion. |
| `defs/sec_forms/cover/checkmark/candidates.py` | 638 | `engine/forms/checkmarks/extractor.py` | Geometry-aware extraction of checkbox boxes (`[ ]`, `[X]`, `✓`, `( )`) and captions. |
| `defs/sec_forms/cover/checkmark/solver.py` | 187 | `engine/forms/checkmarks/solver.py` | **Quadratic Penalty Solver**: Solves statutory filer constraints under contradictory noise. |
| `defs/sec_forms/cover/checkmark/models.py` | 121 | merged into `engine/forms/checkmarks/solver.py` | `PenaltyScorer(binary_xor=1000, primary_exactly_one=1000, report_period=700)`. |
| `defs/sec_forms/cover/checkmark/rewrite.py` | 429 | `engine/forms/checkmarks/rewrite.py` | Rewrites text with canonicalized checkbox symbols while maintaining character offsets. |
| `defs/sec_forms/cover/boundary/detection.py` | 398 | `engine/forms/cover/boundary.py` | Detects transition line separating cover metadata from body prose. |
| `defs/sec_forms/cover/body_start.py` | 481 | `engine/forms/cover/body_start.py` | Structural body start anchor identification. |
| `defs/sec_forms/cover/closing.py` | 117 | `engine/forms/cover/closing.py` | Identifies signature (`SIGNATURES`) and closing spans. |
| `defs/sec_forms/evaluators/` | ~600 | `engine/forms/evaluators/` | Detects Exhibit 13 delegation and stub filings. |
| `defs/sec_forms/normalization/` | ~2,500 | `engine/forms/plugins/` | `FormPlugin` SPI and self-registering form pipelines (10-K, 10-Q, 8-K, XML). |

---

## 3. Detailed Component Specifications

### 3.1. Geometry-First Table Tagging (`edgar_sec/engine/tables/`)
- **Table Masking Sentinel Protocol**:
  1. Detect table spans in HTML or ASCII text.
  2. Replace table spans with sentinel tokens: `__SEC_TBL_{idx}__`.
  3. Run reflow and text normalization exclusively on non-table prose.
  4. Restore table spans formatted inside `<TABLE> ... </TABLE>` tags with pristine column grids intact.

### 3.2. Cover-Page Checkmark Quadratic-Penalty Solver (`edgar_sec/engine/forms/cover/`)
- **The Challenge**: A single Form 10-K cover page may have 20+ statutory checkboxes. OCR errors and HTML rendering bugs frequently cause:
  - Both "Yes" and "No" boxes marked `[X]`.
  - Both "Large Accelerated Filer" and "Non-Accelerated Filer" marked `[X]`.
  - Shell Company marked `[X]` while WKSI is marked `[X]` (statutorily incompatible).
- **The Solution**: A discrete optimization solver that minimizes total penalty across statutory constraints:
  $$\text{Score}(H) = \sum_{r \in \text{Rules}} \text{Weight}(r) \cdot \mathbb{I}(\text{violated}(r, H))$$
  - Binary XOR penalty: 1,000 pts.
  - Primary filer status (exactly one): 1,000 pts.
  - WKSI / Shell mutual exclusion: 5,000 pts.

### 3.3. FormPlugin SPI & Evaluators (`edgar_sec/engine/forms/`)
- Replaces hardcoded conditional branches with a pluggable SPI:
```python
class FormPlugin(ABC):
    form_family: str
    
    @abstractmethod
    def evaluate(self, doc: DocumentRepresentation) -> EvaluatorDecision: ...
    
    @abstractmethod
    def normalize(self, doc: DocumentRepresentation) -> NormalizedDocument: ...
```

---

## 4. Milestone Checklist & Verification

- [x] **M4.1**: Table geometry under `engine/tables/` (`ascii_html/`, `resolver.py`, `structural.py`, `toc.py`, `protection.py`). Shipped in sub-plan 02 under different names than planned; reconciled rather than rebuilt. *Corrected 2026-09-29: this was marked `[x]` while the package did not import at all — v1's `defs/tables/tokens.py` facade was never ported, so five `ascii_html` modules imported four definitions that existed nowhere and no test imported the package. Fixed by porting the four into `numeric_cells.py`; verified by `tests/test_package_imports.py` (added because the gate was blind to a dead package) and `tests/engine/tables/ascii_html/test_renderer.py`.*
- [x] **M4.2**: Checkmark solver under `engine/forms/checkmarks/` (candidates, models, solver, rewrite). Shipped in sub-plan 02 under different names; `PenaltyScorer` settings and the fingerprint/importance heuristic are faithful to v1.
- [x] **M4.3**: Cover region detection — `cover/boundary.py`, `cover/body_start.py`, `cover/closing.py`, plus `structure.py`, `cover_start.py`, `body_search.py`, `body_evidence.py`. **Shipped with the documented scope reductions in §4.**
- [x] **M4.4**: `engine/forms/evaluators/` with `REFETCH_SUB_DOC` support. Ported from v1's `forms/*/evaluator.py` (**347 lines**, not the ~600 originally estimated).
- [x] **M4.5**: `FormPlugin` SPI (`engine/forms/normalize.py` + `engine/forms/plugins/`), seeded with 10-K, 10-Q, 8-K and 20-F.
- [ ] **M4.6**: Replay `.v1/defs/tests/test_cover_checkmark_inference.py` for 100% solver parity. **Open** — requires the real-filing fixtures deferred in M6.3.

> [!IMPORTANT]
> **The composition seam is M4.5, and it is the keystone of the whole phase.**
> Every other engine stage already existed as a pure function; nothing composed
> them. `engine/forms/normalize.py` is the single place the stage order lives, and
> the order follows **v1's actual order** — page policy, cover boundary, checkmark
> rewrite, whitespace, body start, reflow, closing — not the shorthand
> "unpack → HTML clean → table protect → reflow → checkmark" that appeared in the
> original plan. That shorthand put reflow before checkmark, which would have fed
> the solver a stale pre-reflow boundary. All line anchors are remapped through
> `build_line_mapper` afterwards, and the pre-reflow values are reported
> separately as `cover_boundary_detected_line` / `cover_start_detected_line`
> because reflow can renumber lines it collapses.

---

## 4. M4.3: measured scope and two scoped substitutions

The original inventory claimed M4.3 was ~996 lines — `boundary/detection.py` (398)
+ `body_start.py` (481) + `closing.py` (117). Measured on disk, the real
dependency closure of those three files is **~3,265 lines**. They pull in:

| Dependency | Lines | v2 home |
| :--- | ---: | :--- |
| `cover/{structure,rules,cover_start,body_search,body_prose,transition,helpers,finalize}.py` | 1,026 | ported, split across `cover/` to respect the 800-line cap |
| `defs/text/structure/logical_units.py` | 208 | **substituted** (see below) |
| `cover/body_context.py` | 127 | ported into `body_start.py` |
| `cover/toc/` | 938 | **partially substituted** (see below) |
| `defs/text/bow/` (engine, automaton, match, types) | 1,234 | **substituted** (see below) |

### 4.1 Tiered bag-of-words engine → single-tier Aho-Corasick match

`defs/text/bow/` has no v2 port, and reproducing it would have been a 1,234-line
foundation change. v2 *does* have `foundation/text/automaton.py` (421 lines) with
`LexicalMatcher` / `compile_lexical_matcher`, but it compiles **one tier per
category** — so v1's four weighted tiers with minimum-distinct-hit thresholds
cannot be reproduced as written.

**Substitution:** `domain/forms/body_evidence.py` carries a generic tier
vocabulary ported from v1's annual pack (which was a superset of the quarterly
and current-report packs for every tier the boundary actually consults), and
`engine/forms/cover/body_evidence.py` scores distinct hits onto **v1's same 0-3
scale**, keeping the cover-exclusion veto that v1 had. Two strong terms or one
strong phrase clear the gate, exactly as in v1.

### 4.2 Logical-unit classifier → line-level gates

v1's `find_body_start` used `classify_units` to know whether a candidate line sat
inside a table, list, signature, or TOC unit. v2 has no unit classifier, so unit
context is approximated by line-level structural and lexical gates that encode the
same distinctions.

### 4.3 TOC span finder → heading-based transition

v1's strongest signal consulted `find_toc_span` from a 938-line TOC subsystem with
no v2 home. v2's `TOC_TRANSITION` uses the heading-based path instead, reusing the
TOC *primitives* that `engine/tables/toc.py` already provides. The signal still
fires — one signal later, and without the confidence refinement.

### 4.4 `closing.py` ported faithfully

Every dependency it needs already exists in v2 (`is_toc_row`, `RE_TOC_LEADER`,
`RE_PAGE_NUMBER_SUFFIX`, `RE_CONFORMED_SIGNATURE`), so it required no substitution.

---

## 5. A v2-specific trap found during the port

v2's `RE_PAGE_NUMBER_SUFFIX` matches a trailing **Roman numeral**, so a bare
`PART I` line satisfies it and `engine/tables/toc.py::looks_like_toc_row("PART I")`
returns `True`. v1 never applied a text-level TOC test to structural heading
candidates — it used a TOC-span/unit check — so this trap is specific to v2's
table-cell-oriented helper and would have silently rejected every PART heading,
leaving the boundary unable to fall back at all.

Fixed by splitting the notion in two:

- `is_toc_layout_line` (**strict**) — a dot leader with a page suffix, or a page
  suffix leaving a multi-word title. Used to validate structural heading
  candidates. `PART I` and `ITEM 1` are correctly headings.
- `is_toc_like_line` (**v1's loose backward-search semantics**, which include the
  bare `ITEM` reference check). Never applied to a heading candidate.

Pinned by `tests/engine/forms/cover/test_body_start.py` and
`tests/engine/forms/test_normalize.py`.
