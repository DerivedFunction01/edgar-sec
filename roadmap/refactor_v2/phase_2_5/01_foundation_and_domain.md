# Phase 2.5 — Sub-Plan 01: Foundation Text & Domain Models

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Layer Focus:** Layer 0 (`foundation/text/`, `foundation/regex/`) and Layer 1 (`domain/document/`, `domain/forms/`)  
> **Source Grounding:** `.v1/defs/text/`, `.v1/defs/regex/`, `.v1/defs/sec_documents/records.py`, `.v1/defs/sec_forms/cover/checkmark/schemas.py`

---

## 1. Objectives & Architectural Role

Before document parsing or SQLite chunk storage can begin, Phase 2.5 requires:
1. **Zero-SEC text and regex primitives (Layer 0)**: High-performance single-pass multi-pattern searching (Aho-Corasick), statutory compound word dictionaries, hyphenation healing, and regex alternation optimization.
2. **Pure domain leaf models (Layer 1)**: Content-addressed document locators, occurrence aggregates, typed block stream representations (`DocumentBlock`), and statutory checkbox constraint schemas.

These modules have **zero dependencies on database drivers, HTTP clients, or downstream pipelines**.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Invariants |
| :--- | ---: | :--- | :--- |
| `defs/text/bow.py` | 338 | `foundation/text/automaton.py` | **Aho-Corasick Automaton**: Single-pass $O(T + \text{matches})$ lexical scanning over token streams without regex backtracking. |
| `defs/text/compounds.py` | 185 | `foundation/text/compounds.py` | Statutory compound words ("Form 10-K", "Item 1A", "Exhibit 13") and soft-hyphen word healing. |
| `defs/text/normalize.py` | 195 | `foundation/text/normalize.py` | Unicode NFKD normalization, non-breaking space collapsing, control character stripping, and clean ASCII conversion. |
| `defs/regex/trie.py` | 120 | `foundation/regex/trie.py` | Builds compact prefix-tree regex alternations (e.g. `(?:apple|application)` &rarr; `appl(?:e|ication)`). |
| `defs/sec_documents/records.py` | 145 | `domain/document/models.py` | `DocumentLocator`, `FilingOccurrence`, `DocumentRepresentation`, `DocumentKind` (`HTML`, `ASCII_TXT`, `XML`). |
| *New in v2 (Track 2)* | — | `domain/document/blocks.py` | **Flat 1D Typed Block Stream**: `ParagraphBlock`, `TableBlock`, `PreservedBlock`, `PageBreakMarker`. Decoupled from Phase 03 TOC Spine. |
| `defs/sec_forms/cover/checkmark/schemas.py` | 116 | `domain/forms/schemas.py` | Declarative `STATUTORY_CHECKBOX_CONSTRAINTS` (7 statutory relations: WKSI exclusion, 404(b) exemption, etc.). |
| `defs/sec_forms/evaluators/base.py` | 85 | `domain/forms/decisions.py` | `DecisionAction` enum (`ACCEPT`, `REFETCH_EXHIBIT`, `REFETCH_BUNDLE`, `REFETCH_SUMMARY_XML`) and `EvaluatorDecision`. |

---

## 3. Detailed Component Specifications

### 3.1. Foundation: Aho-Corasick Automaton (`edgar_sec/foundation/text/automaton.py`)
- **Problem in SEC Parsing**: Filings range from 2MB to 100MB. Scanning for hundreds of statutory terms (item headings, checkbox captions, accounting terms) via repeated regex matches causes quadratic $O(N \cdot M)$ slowdowns.
- **Contract**:
  ```python
  class LexicalAutomaton:
      def __init__(self, patterns: dict[str, Any]): ...
      def find_matches(self, text: str) -> list[tuple[int, int, str, Any]]:
          """Returns list of (start_idx, end_idx, matched_pattern, payload) in single pass."""
  ```

### 3.2. Foundation: Compound Word & Hyphenation Healing (`edgar_sec/foundation/text/compounds.py`)
- **Contract**: Reconstructs compound phrases split across line breaks or wrapped with soft hyphens (e.g. `"inter-  \n  company"` &rarr; `"intercompany"`).
- Uses immutable frozen set dictionaries for financial statutory compounds.

### 3.3. Domain: Document Leaf Models (`edgar_sec/domain/document/models.py`)
```python
from dataclasses import dataclass
from enum import Enum
from edgar_sec.domain.identity import AccessionNumber, Cik

class DocumentKind(Enum):
    HTML = "html"
    ASCII_TXT = "ascii_txt"
    XML = "xml"

@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """Unique content-addressed reference to a filing document."""
    accession: AccessionNumber
    document_path: str
    document_locator_key: str  # sha256(accession + ":" + document_path)

@dataclass(frozen=True, slots=True)
class FilingOccurrence:
    """Materialized filing observation linking a CIK to a document locator."""
    occurrence_id: str         # sha256(source_cik + ":" + document_locator_key)
    source_cik: Cik
    locator: DocumentLocator
    form: str
    filing_date: str
    is_amendment: bool
```

### 3.4. Domain: Flat 1D Block Stream (`edgar_sec/domain/document/blocks.py`)
```python
from dataclasses import dataclass
from enum import Enum

class BlockKind(Enum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    PRESERVED = "preserved"
    PAGE_BREAK = "page_break"

@dataclass(frozen=True, slots=True)
class DocumentBlock:
    block_index: int
    kind: BlockKind
    text: str
    raw_lines: tuple[str, ...]
    char_start: int
    char_end: int
```

---

## 4. Milestone Checklist & Verification

- [x] **M1.1**: Create `edgar_sec/foundation/text/normalize.py` and `compounds.py`.
- [x] **M1.2**: Create `edgar_sec/foundation/text/automaton.py` and verify $O(N)$ scanning with unit tests.
- [x] **M1.3**: Create `edgar_sec/foundation/regex/trie.py` alternation optimizer.
- [x] **M1.4**: Create `edgar_sec/domain/document/models.py` and `blocks.py`.
- [x] **M1.5**: Create `edgar_sec/domain/forms/schemas.py` and `decisions.py`.
- [x] **M1.6**: Run offline unit tests in `tests/foundation/` and `tests/domain/`.
- [x] **Verification**: Run `python check.py --scan` to guarantee zero upward dependencies from Layer 0 and Layer 1.
