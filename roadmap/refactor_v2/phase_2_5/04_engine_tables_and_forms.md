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
3. **Delegation Evaluators (`engine/forms/evaluators/`)**: Detects filings that incorporate key disclosures by reference or delegate them to Exhibit 13, returning multi-scope actions (`REFETCH_EXHIBIT`).
4. **FormPlugin SPI (`engine/forms/plugins/`)**: Self-registering plugins providing form-specific normalization pipelines for 10-K, 10-Q, 8-K, 6-K, 20-F, Form 3/4/5, and Form 13F.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Invariants |
| :--- | ---: | :--- | :--- |
| `defs/tables/detector.py` | 380 | `engine/tables/detector.py` | Geometry-first table detection: column gaps, header alignments, numeric densities. |
| `defs/tables/grid.py` | 260 | `engine/tables/grid.py` | 2D cell grid estimation and tagged table delimiter insertion. |
| `defs/sec_forms/cover/checkmark/candidates.py` | 638 | `engine/forms/cover/candidates.py` | Geometry-aware extraction of checkbox boxes (`[ ]`, `[X]`, `✓`, `( )`) and captions. |
| `defs/sec_forms/cover/checkmark/solver.py` | 187 | `engine/forms/cover/solver.py` | **Quadratic Penalty Solver**: Solves statutory filer constraints under contradictory noise. |
| `defs/sec_forms/cover/checkmark/models.py` | 121 | `engine/forms/cover/models.py` | `PenaltyScorer(binary_xor=1000, primary_exactly_one=1000, report_period=700)`. |
| `defs/sec_forms/cover/checkmark/rewrite.py` | 429 | `engine/forms/cover/rewrite.py` | Rewrites text with canonicalized checkbox symbols while maintaining character offsets. |
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

- [ ] **M4.1**: Implement `edgar_sec/engine/tables/detector.py` and `grid.py`.
- [ ] **M4.2**: Port `edgar_sec/engine/forms/cover/checkmark/` (candidates, models, solver, rewrite).
- [ ] **M4.3**: Port boundary detection (`boundary.py`, `body_start.py`, `closing.py`).
- [ ] **M4.4**: Implement `engine/forms/evaluators/` with `REFETCH_EXHIBIT` action support.
- [ ] **M4.5**: Implement `FormPlugin` SPI and register core forms (10-K, 10-Q, 8-K).
- [ ] **M4.6**: Replay `.v1/defs/tests/test_cover_checkmark_inference.py` to verify 100% solver parity.
