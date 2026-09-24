# Reflow Prose vs. Table Classification Hypotheses

This document records the linguistic, geometric, and structural hypotheses for distinguishing **hard-wrapped narrative prose** (intended for unwrapping) from **tabular or structured layout blocks** (intended for preservation) within SEC EDGAR filings.

---

## 1. Physical Layout Invariants & The 80-Column ASCII Constraint

In legacy ASCII SEC filings, documents are formatted against an ~80-character terminal width boundary.
Wide tables (> 80 characters, e.g., complex multi-column financial statements) are required by EDGAR submission standards to be enclosed in `<TABLE>` tags, which are already detected and protected upstream by `mask_tagged_tables`.

Therefore, the ambiguous layout blocks evaluated by reflow are **unprotected blocks fitting within ~80 characters**. Under this boundary constraint, two mutually exclusive layout paradigms exist:

```text
A. Hardwrapped Continuous Prose (Single-column layout, spans cols 0 to ~78)
col 0                                                      col 75-80
┌─────────────────────────────────────────────────────────────┐
│ The Company entered into a definitive credit agreement with │ ── Line X ends in dangling connector ("with")
│ the lenders on March 15, 1998, providing for borrowings up  │ ── Line Y starts flush-left (col 0), lowercase
│ to $50.0 million to finance working capital requirements.   │ ── Line width fills margin (68–79 chars)
└─────────────────────────────────────────────────────────────┘
  • Continuation Indent Invariant: Line 0 may have an initial paragraph indent (e.g. 2–5 spaces), but all continuation lines (Lines 1..N-1) share an identical uniform indent (whether 0 spaces, 2 spaces, or tabs)
  • Line width: Non-final lines uniformly fill 65–80 chars
  • Vertical gutter: NONE (words break naturally at word boundaries)

B. Bilaterally Indented Prose (Blockquotes, Excerpts, Justified / Inset Text)
col 0     col 4-10                                       col 65-72    col 80
┌─────────┬──────────────────────────────────────────────┬────────────┐
│         │ "RESOLVED, that the officers of the Company   │            │ ── Line X ends in dangling connector ("to")
│         │ are hereby authorized and directed to execute│            │ ── Line Y starts at left margin L (col 8)
│         │ and deliver the aforementioned Agreement..." │            │ ── Uniform bilateral bounding box [L, R]
└─────────┴──────────────────────────────────────────────┴────────────┘
          ▲                                              ▲
          └────── Uniform Left Inset Margin (L)          └────── Uniform Right Inset Margin (R)
  • Bilateral Inset Invariant: In financial printing, certain narrative passages (contract excerpts, indenture definitions, board resolutions, or justified text blocks) are indented on BOTH the left and the right margins (e.g., left margin L >= 4 spaces, right margin wrapping at R <= 72).
  • Monomorphic Bounding Box: Although inset from the 0–80 borders, all continuation lines share the identical left margin L and wrap near the uniform right margin R. Within the text corridor [L, R], there is NO internal vertical gutter, words flow continuously, and syntactic soft-wrapping occurs from line X to line X+1.

C. Multi-Column Table with Prose Column (e.g., 2 columns fitting in 80 chars)
col 0            col 20    col 24                           col 80
┌────────────────┬────────┬───────────────────────────────────┐
│ March 15, 1998 │        │ Credit agreement with lenders for │ ── Row 1
│                │        │ borrowings up to $50.0 million.   │ ── Row 1 Cell wrap: Indented to col 24!
│ April 20, 1998 │        │ Acquisition of widget business.   │ ── Row 2: Col 0 reset, new entry
└────────────────┴────────┴───────────────────────────────────┘
                 ▲        ▲
                 └────────┴── Invariant Vertical Gutter (Col 20–24 is blank across lines)
  • Indent of Line Y (cell wrap): >= 12–24 cols (indented to match column start)
  • Width of Column 2: Capped at ~56 chars (cannot span 75+ chars starting from col 0)
  • Inter-row syntax: Row 1 never grammatically continues into Row 2
```

### The Typographic Measure & Regulatory Mandate (Why Untagged Multi-Column Prose Does Not Exist)
- **The Typographic "Measure" Constraint**: In typography, the ergonomic standard for English prose reading is 45 to 75 characters per line (approx. 9–12 words). If a filer attempted to format two side-by-side prose columns within an 80-character boundary:
  $$\text{Col 1 (36 chars)} + \text{Gutter (5 chars)} + \text{Col 2 (36 chars)} = 77 \text{ chars}$$
  Each column would hold only 4 to 6 words per line. Narrative prose formatted at 4–6 words per line produces extreme typographical fragmentation, awkward hyphenations, and unreadable "rivers" of white space. A 3-column prose layout ($\approx 22$ chars/col) would hold only 2–3 words per line.
- **SEC Regulatory & Filer Manual Rules**: Under SEC Rule 403 and Rule 420, disclosures must be clearly legible and presented to avoid misleading formatting. The SEC EDGAR Filer Manual explicitly mandated that any multi-column layout or comparison table must use `<TABLE>` and `<CAPTION>` tags.
- **Deductive Invariant**: Corporate issuers and financial printers (RR Donnelley, Bowne, Merrill) never submitted multi-column prose disclosures in raw ASCII without `<TABLE>` tags. Any untagged 80-column block with lines extending past column 60 is structurally and historically guaranteed to be single-column text.

---

## 2. Macro Hypotheses: Double-Newline (`\n\n`) Passage Boundaries

A layout block may contain multiple passages separated by double newlines (`\n\s*\n`). Evaluating at the passage boundary isolates discrete semantic units:

### H-MACRO-1: Passage Termination Invariant
- **Hypothesis**: A genuine narrative prose passage ends with terminal sentence punctuation (`.`, `!`, `?`, or quotes `."`, `?"`), whereas a table passage ends with numeric values, currency symbols, parentheses, percentages, or column blanks.
- **Empirical Measure**:
  - Reflow Candidates: **78.4%** end with terminal sentence punctuation; only **7.2%** end with numeric/paren tokens.
  - Tables: Only **7.5%** end with sentence punctuation; **33.3%** end with numeric/paren tokens (the remainder end in dashes, blanks, or underlines).

### H-MACRO-2: Grammatical vs. Numeric Comma Ratio
- **Hypothesis**: In prose, commas serve as syntactic clause separators (`[a-zA-Z], [a-zA-Z]`). In tabular blocks, commas predominantly serve as numeric thousand separators (`\d,\d{3}`).
- **Formulas**:
  $$\text{Ratio} = \frac{\text{Count}(\text{Grammatical Commas})}{\text{Count}(\text{Grammatical Commas}) + \text{Count}(\text{Numeric Commas})}$$
- **Empirical Measure**:
  - Reflow Candidates: Median ratio = **0.86**.
  - Tables: Median ratio = **0.00**.

### H-MACRO-3: Subordinate Clauses and Relative Pronouns
- **Hypothesis**: Subordinating conjunctions and relative pronouns (`which`, `that`, `who`, `whose`, `whom`, `whereby`, `wherein`) introduce complex narrative dependencies that are characteristic of prose and absent in tabular records.
- **Empirical Measure**:
  - Reflow Candidates: **82.5%** contain relative clause markers.
  - Tables: **26.6%** (concentrated primarily in narrative footnotes).

### H-MACRO-4: Possessive Nouns
- **Hypothesis**: English possessives (`'s`, `s'`) occur in narrative descriptions of corporate entities, agents, and products, but rarely in tabular rows.
- **Empirical Measure**:
  - Reflow Candidates: **59.3%** contain possessive tokens.
  - Tables: **11.2%**.

### H-MACRO-5: Semicolon Density
- **Hypothesis**: Semicolons (`;`) connect independent clauses or delimit complex narrative lists in prose, but are almost never used in data tables.
- **Empirical Measure**:
  - Reflow Candidates: **18.0%** contain semicolons.
  - Tables: **2.6%**.

### H-MACRO-6: Article Density
- **Hypothesis**: The presence of definite and indefinite articles (`the`, `a`, `an`) per line reflects continuous English prose grammar.
- **Empirical Measure**:
  - Reflow Candidates: Median **1.33 articles per line**.
  - Tables: Median **0.25 articles per line**.

---

## 3. Micro Hypotheses: Single-Newline (`\n`) Line Wraps within Passages

Within an 80-column passage, line-by-line wrapping behavior reveals whether line breaks are soft word wraps or discrete tabular rows:

### H-MICRO-1: Inter-Line Syntactic Continuation
- **Hypothesis**: In hardwrapped prose, Line $i$ ends with an alphanumeric word or clause comma `,` and Line $i+1$ begins with a lowercase letter (or normal continuation word). In tables, lines are self-contained entries that do not begin with lowercase continuation words.
- **Empirical Measure**:
  - Reflow Candidates: **32.7%** of lines exhibit direct alpha $\to$ lowercase inter-line continuation.
  - Tables: **4.9%** (and median **0.0%**).

### H-MICRO-2: Dangling Syntactic Connectors at Line Ends
- **Hypothesis**: A line in continuous prose frequently ends on a function word whose syntactic completion is required on the next line:
  - Determiners: `the`, `a`, `an`
  - Prepositions: `of`, `to`, `in`, `for`, `with`, `by`, `from`, `under`, `between`, `against`
  - Conjunctions: `and`, `or`, `that`, `which`, `as`
  - Hyphenated words: `short-`, `inter-`, `well-`
- **Empirical Measure**:
  - Reflow Candidates: **57.7%** of blocks have $\ge 1$ open connector line wrap (averaging **17.9%** of all line wraps).
  - Tables: **29.2%** of blocks have any connector wrap (averaging only **2.8%** of lines, mostly in footnote blocks).

### H-MICRO-3: Line End Character Distribution
- **Hypothesis**: Tabular rows terminate in numeric amounts, parenthesized negatives, percentages, or dashes. Prose lines terminate in letters or standard punctuation.
- **Empirical Measure**:
  - Reflow Candidates: Only **8.7%** (median **1.6%**) of lines end in digits, `)`, or `%`. **49.2%** of lines end in raw letters (soft wraps).
  - Tables: **37.6%** (median **38.9%**) of lines end in digits, `)`, or `%`. Only **19.6%** of lines end in raw letters.

### H-MICRO-4: Right-Zone (Cols 45–80) Prose Word Occupancy
- **Hypothesis**: In an 80-column layout, the right half of a table is reserved for numeric columns. In hardwrapped prose, words occupy the entire 0–80 column span.
- **Empirical Measure**:
  - Reflow Candidates: **82.9%** have common English stopwords (`the`, `and`, `of`, `to`...) in columns 45–80. **97.9%** contain alpha words in columns 45–80.
  - Tables: Only **14.1%** have stopwords in columns 45–80.

### H-MICRO-5: Line Indentation Uniformity vs. Cell Indentation
- **Hypothesis**: In hardwrapped prose, continuation lines (lines $1 \dots N-1$) return to column 0–4 (flush left). In a table with a wrapped prose column, continuation lines are indented $\ge 12$ columns to clear the left stub column.
- **Empirical Measure**:
  - Reflow Candidates: **68.9%** of continuation lines start at column $\le 4$; only **6.8%** have large indents ($\ge 12$).
  - Tables: **30.8%** of continuation lines have large indents ($\ge 12$ spaces).

### H-MICRO-6: Continuation Line Indent Invariance (Left-Margin Monomorphism)
- **Hypothesis**: In any narrative prose passage, the first line (Line 0) may exhibit an optional paragraph indent (e.g., 2–5 spaces or 1 tab) or start flush left. However, all subsequent continuation lines (Lines $1 \dots N-1$) **must share an identical, uniform left-margin indent** (whether 0 spaces, 2 spaces, 4 spaces, or 1 tab), establishing a singular margin boundary for the body of the paragraph. Conversely, in multi-column tables, line indents vary frequently because lines alternate between row headers, indented cell wraps, and shifted column offsets.
- **Empirical Measure**:
  - Reflow Candidates: **65.5%** of multi-line passages have strictly identical indents across all continuation lines.
  - Ordinary Prose: **65.8%** have strictly identical indents across all continuation lines.
  - Tables: Only **28.9%** of multi-line table passages maintain a single uniform indent across continuation lines.

### H-MICRO-6b: Bilateral (Dual-Margin) Indentation in Inset & Justified Prose Blocks
- **Hypothesis**: In narrative prose disclosures, certain passages are formatted as blockquotes, contract excerpts, statutory provisions, cautionary legends, or justified insets where margins are indented on **both the left and the right** (e.g., left margin $L \ge 4$ spaces, right boundary $R \le 72$ chars).
  - Rather than filling the default $[0, 80]$ column canvas, bilateral prose fills an inset typographic window $[L, R]$ of width $W = R - L$ (typically 45–65 characters).
  - **Monomorphic Inset Geometry**: All continuation lines (Lines $1 \dots N-1$) share an identical left indent $L$ and non-final lines terminate consistently near right margin $R$.
  - **Differentiation from Tables**:
    1. **Absence of Internal Gutters**: Within the active text span $[L, R]$, there are no persistent multi-space column gaps (no vertical whitespace corridor).
    2. **Syntactic Soft Wrap**: Lines wrap from $(X, R) \to (X+1, L)$ with grammatical clause flow (open connectors, prepositions, hyphens, lowercase continuation starts).
    3. **Contrast with Indented Tables**: Indented tables or specification lists (e.g., indented key-value pairs) contain internal gutters separating labels from values, or terminate lines in numbers, dashes, and discrete units.
- **Empirical Measure**:
  - Bilateral indented blocks occur in **5.9%** ($91/1{,}542$) of ordinary prose and **4.1%** ($8/194$) of candidates.
  - In genuine bilateral prose, **100%** of continuation lines share the identical left margin $L$ and show soft-wrap syntactic flow, whereas indented tables exhibit internal gutters and row-item independence.

### H-MICRO-7: Window 2/3 (Cols 20–60) Mid-Zone Invariants
- **Hypothesis**: In an 80-column line, columns 20 to 60 represent the "dead zone" or gutter corridor for multi-column tables. The presence of continuous English words, prepositional phrases (`as a result of`, `pursuant to`, `in connection with`), and grammatical clause commas (`[a-z], [a-z]`) in this middle window physically obliterates the column gutter required by a 2+ column table.
- **Empirical Measure**:
  - Gutter Absence ($\ge 3$ consecutive spaces): **91.5%** of candidate lines have NO gutter in cols 20–60 (vs. only 21.4% in tables; 78.6% of table lines contain mid-zone gutters).
  - Pure-Alpha Mid-Zone ($\ge 4$ words, 0 numbers): **97.9%** of candidate blocks have pure-alpha lines spanning cols 20–60 (vs. 38.3% in tables).
  - Grammatical Clause Commas in Mid-Zone: **75.9%** in candidates vs. 29.3% in tables.

### H-MICRO-8: The 50-Column Wall in Inverse Tables (Col 1 Prose, Col 2 Numeric)
- **Hypothesis**: If an 80-column table has a prose description in Column 1 and numeric data in Column 2, the numeric column and gutter consume columns ~50 to 80. Consequently, all wrapped description lines in Column 1 are artificially capped at column $\le 50$, leaving columns 50–80 completely empty. In hardwrapped prose, non-final lines do not truncate at column 50; they flow unbroken through columns 60, 70, and 75+.
- **Empirical Measure**:
  - Lines flowing unbroken past Col 70+: **80.9%** of lines in candidates (92.3% of blocks) vs. only **15.7%** in tables.
  - Stub $\to$ Gutter $\to$ Numeric Cell transitions: **25.4%** of lines in tables vs. only **1.0%** in candidates.
  - Premature truncation at Col $\le 50$: **27.0%** of lines in tables vs. only **9.3%** in candidates.

### H-MICRO-9: Top-Aligned Multi-Line Rows and Mid-Zone Whitespace Asymmetry
- **Hypothesis**: In tables employing top-alignment (the numeric data cell sits on Line 1, while Line 2 contains the wrapped text description), the middle zone (cols 20–60) exhibits an extreme whitespace asymmetry:
  - **Line 1 (Top Data Line)**: Spans cols 0 to $\ge 70$, containing a multi-space column gutter ($\ge 10$ spaces) or leader dots (`\.{3,}`) in cols 25–60 bridging the description to the numeric cell.
  - **Line 2 (Continuation Line)**: Exhibits an extreme concentration of whitespace in the middle zone: either early truncation at column $\le 45$ (leaving cols 45–80 dead space) or large leading indentation ($\ge 35$ spaces) aligning with Column 2's margin.
  - **Line-Length Differential**: $\Delta \text{Length} = \text{Length}(\text{Line 1}) - \text{Length}(\text{Line 2}) \ge 25\text{--}45$ characters, violating continuous prose wrapping where non-final lines maintain uniform length.
- **Empirical Measure**:
  - Tables: **401 blocks** containing **1,248 top-aligned row instances**.
  - Prose & Candidates: **0 blocks (0 instances)**.
  - Demonstrates 100% mutual exclusivity with candidate prose blocks.

---

## 4. Special Structures and Invariant Boundaries

### H-SPEC-1: Exhibit Index Identification & Exclusion
- **Characteristics**:
  - Section headers: `EXHIBIT INDEX`, `INDEX TO EXHIBITS`, `ITEM 14(a)(3) - EXHIBITS`
  - Left column numbering: `10.1`, `10.2`, `10(24)`, `23.1`
  - Boilerplate phrases: `Filed as Exhibit...`, `incorporated herein by reference`, `Filed herewith`
- **Treatment**:
  - Exhibit indices often contain narrative descriptions in their description column, yielding high prose scores.
  - Detecting exhibit numbering and phrases allows separating them from standard narrative prose to preserve their tabular structure.

### H-SPEC-2: Tagged Narrative Disclosures
- **Characteristics**:
  - Notes to financial statements or legal proceeding disclosures (e.g. *Commitments and Contingencies*) enclosed in `<TABLE>` tags for legacy margin formatting.
- **Treatment**:
  - Because these disclosures contain `<TABLE>` wrapper tags, they are automatically protected by `mask_tagged_tables` and do not enter the ambiguous candidate pool.

---

## 5. Interline Syntactic & Collocation Dependencies (Split N-Grams and Entities)

In hardwrapped prose, an ~80-character margin causes tightly bound English collocations, multi-word entities, and syntactic dependencies to fracture across consecutive lines (Line $X \to$ Line $X+1$). In tabular layouts, rows are self-contained records that do not fracture these multi-token expressions across row boundaries.

### H-INTER-1: Split Fixed Collocations & Prepositional Idioms
- **Hypothesis**: Multi-word functional expressions frequently split across the line break:
  - `in connection` // `with`
  - `in accordance` // `with`
  - `as a result` // `of`
  - `pursuant` // `to`
  - `with respect` // `to`
  - `in order` // `to`
  - `as set forth` // `in`
  - `subject` // `to`
  - `from time` // `to time`
  - `as well` // `as`
  - `based` // `on` / `upon`
- **Empirical Measure**:
  - Reflow Candidates: **10.8%** of blocks contain a split prepositional collocation across lines.
  - Tables: **4.2%** (concentrated in narrative footnote rows).

### H-INTER-2: Split Dates & Temporal Periods
- **Hypothesis**: Complete date expressions split across the margin break, with the month terminating Line $X$ and the day/year heading Line $X+1$:
  - `December` // `31, 1999`
  - `March` // `31, 2001`
  - `three months` // `ended September 30`
- **Empirical Measure**:
  - Reflow Candidates: **6.7%** of blocks exhibit split calendar dates.
  - Tables: Only **1.5%** (dates in tables are typically self-contained within a column cell).

### H-INTER-3: Split Verb Phrases (Auxiliary / Modal → Main Verb)
- **Hypothesis**: Modal or aspectual auxiliaries at the end of Line $X$ govern a participle or infinitive verb at the start of Line $X+1$:
  - Modals: `will` // `be delivered`, `shall` // `be entitled`, `would` // `result`, `may` // `require`
  - Aspect/Passive: `has` // `been designated`, `was` // `entered into`, `are` // `calculated`
  - Infinitives: `to` // `finance`, `to` // `satisfy`
- **Empirical Measure**:
  - Reflow Candidates: **17.5%** of blocks contain an auxiliary/modal-to-verb split.
  - Tables: Only **1.2%**.

### H-INTER-4: Split Noun Phrases (Determiners & Modifiers → Head Noun)
- **Hypothesis**: Determiners, possessives, and attributive modifiers at the line terminal syntactically govern the head noun on the subsequent line:
  - Articles/Demonstratives: `the` // `Company`, `a` // `material adverse effect`, `this` // `Agreement`, `such` // `transactions`
  - Possessives: `Company's` // `common stock`, `employee's` // `employment agreement`
  - Quantifiers: `any` // `claims`, `all` // `outstanding shares`, `each` // `director`

### H-INTER-5: Split Enclosures (Unclosed Quotes & Parentheses)
- **Hypothesis**: Parentheses or quotation marks that open on Line $X$ without closing before the end of the line are resolved on Line $X+1$:
  - `(collectively, the` // `"Purchasers")`
  - `referred to as the` // `"Merger Agreement"`
- In tables, cells almost universally close their parentheses (e.g., `$(1,500)` or `(1)`) on the same line.

### H-INTER-6: Syllabic Hyphenation and Compound Word Division
- **Hypothesis**: Words hyphenated at the right terminal margin represent linguistic word division:
  - Syllabic division: `infor-` // `mation` $\to$ `information`, `manage-` // `ment` $\to$ `management`
  - Compound adjectives: `market-` // `sensitive`, `forward-` // `looking`, `third-` // `party`, `short-` // `term`
  - Regulatory filings IDs: `File No. 1-` // `10740`, `Schedule 14D-` // `1`
- **Validation Architecture**:
  - **Tier 1 (Fast Seed Set)**: A ~100-word immutable set of the most frequent financial/legal words subject to division (`information`, `management`, `operations`, `transactions`, `securities`, `approximately`, `consolidated`, etc.) plus common SEC compounds (`forward-looking`, `short-term`, `third-party`).
  - **Tier 2 (LRU Cache + NLTK Dictionary)**: A `@lru_cache(maxsize=256)` wrapping the full NLTK English word dictionary ($234{,}377$ words). On a candidate wrap `head-` // `tail`, verify if `head + tail` or `head + "-" + tail` is a valid English word.
- **Empirical Measure**:
  - **Tables**: Contain **5,618 lines** ending in hyphens. However, **>99.5%** are horizontal column divider rules (`-----------`) or empty numeric cell markers (`-`). True alpha-word hyphenation is virtually absent in tabular data rows.
  - **Prose & Candidates**: Word-level hyphenation at line-ends is relatively rare (<0.1% of lines) because word-processing software used for EDGAR ASCII conversion predominantly wrapped at whole-word boundaries without hyphenation. When it does occur, it splits compound adjectives (`market-` // `sensitive`) or regulatory form identifiers (`Schedule 14D-` // `1`), with 100% precision when validated against the 2-tier English dictionary.

---

### H-INTER-7: Numeric Line End to Unit Word Transition (The Casing Invariant)
- **Hypothesis**: When Line $X-1$ ends with a numeric or currency token (`\$\d+` or `\d+`) and Line $X$ begins with a unit word (`million`, `shares`, `thousands`, `percent`), the casing of the unit word definitively separates prose from tabular row transitions:
  - **In Prose**: The unit word is strictly **lowercased** (`$24.6` // `million`, `1,660,786` // `shares`), forming an unbroken English quantified noun phrase across the soft wrap.
  - **In Tables**: The unit word is strictly **CAPITALIZED** (`1,043` // `Shares redeemed`, `$3.50` // `Options granted`), representing a new independent line-item row with its own numeric values on the right.
- **Empirical Measure**:
  - Reflow Candidates: **100.0%** (33 of 33) of transitions are **lowercased**; 0.0% are capitalized.
  - Tables: **67.8%** are **CAPITALIZED** row headers; the remaining 32.2% are narrative footnotes inside `<TABLE>` tags.

### H-INTER-8: Line Transition Asymmetry (Numeric End → Capitalized vs. Lowercase Start)
- **Hypothesis**: In tables, a line ending with a number is a row completion; the next line starts the next row, which almost always begins with a capitalized line-item title. In hardwrapped prose, numbers appear mid-sentence and flow into lowercased continuations.
- **Empirical Measure** ($N=40{,}078$ table transitions vs. $4{,}160$ candidate transitions):
  - Tables: `Numeric End → Capitalized Start` is **19.3%** ($7,753$ occurrences); `Numeric End → Lowercase Start` is only **0.9%** ($379$ occurrences) $\implies$ **20.5 : 1 ratio**.
  - Candidates: `Numeric End → Lowercase Start` is **1.9%** ($79$ occurrences), exceeding `Numeric End → Capitalized Start` at **1.6%** ($66$ occurrences) $\implies$ **0.84 : 1 ratio**.
  - Soft Wrap (`Alpha End → Lowercase Start`): **23.5%** in candidates vs. only **7.3%** in tables.

### H-INTER-9: Virtual Boundary Join Window
- **Hypothesis**: A virtual join window spanning the line boundary:
  $$\text{Window} = \text{tail}(\text{Line } X, k=2\text{ words}) + \text{" "} + \text{head}(\text{Line } X+1, k=2\text{ words})$$
  resolves broken grammatical dependencies and collocations that cannot occur across table rows:
  - `determiner_noun`: `the` // `Company`, `such` // `transactions`, `this` // `Agreement`
  - `verb_phrase`: `will` // `provide`, `has` // `been`, `may` // `result`, `is` // `based`
  - `date_continuity`: `December` // `31, 1999`, `March` // `31, 2001`
  - `number_to_measure`: `$50.0` // `million`, `10,000` // `shares`, `12.5` // `percent`
- **Empirical Measure**:
  - Reflow Candidates: **83.0%** of blocks exhibit at least one validated grammatical join in the boundary window.
  - Tables: Only **26.4%** (concentrated in narrative footnote rows).

---

## 6. Advanced Two-Dimensional Geometric Hypotheses (H-GEO-7 to H-GEO-18)

These hypotheses extend the geometric analysis from one-dimensional character counts to two-dimensional spatial topology, grid stability, and rewrapping physics:

### Summary of Geometric Hypotheses & Validation Benchmark ($N=3{,}647$ Blocks)

| ID | Hypothesis | Table Signal | Prose Signal | Tables | Ordinary Prose | Candidates | Empirical Verdict |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **H-GEO-7** | **Occupancy topology** | Multiple long non-space runs separated by column gutters ($\ge 4$ spaces) | One continuous text corridor; spaces are single word breaks | **53.5%** | **6.9%** | **13.7%** | **STRONGLY VALID** ($7.8\times$ separation) |
| **H-GEO-8** | **Vertical seam coverage** | Gap positions recur across many rows within small tolerance ($\pm 1$) | Gaps are isolated or drift continuously across lines | **75.9%** | **51.2%** | **44.0%** | **MODERATE** ($1.7\times$ separation) |
| **H-GEO-9** | **Column char-class stability** | Fixed column zones consistently contain labels, numbers, or blanks | Character classes shift across line canvas with no stable column zone | **71.8%** | **74.9%** | **70.2%** | **WEAK** (uniform without windowing) |
| **H-GEO-10** | **Numeric-anchor precision** | Numeric starts, decimal points, or right edges have low positional variance | Numbers occur at varying positions inline within sentences | **23.7%** | **5.8%** | **41.4%\*** | **MODERATE** ($4.1\times$ vs. prose) |
| **H-GEO-11** | **Row-template periodicity** | Normalized row shapes repeat (e.g., `Words -> Num -> Num`) | Consecutive lines have varied token and character-class shapes | **29.6%** | **15.8%** | **19.1%** | **MODERATE** ($1.9\times$ separation) |
| **H-GEO-12** | **Indent transition grammar** | Indentation alternates between row starts and wrapped cell continuations | Continuation lines maintain one stable indent (monomorphism) | **6.8%** | **1.2%** | **2.2%** | **VALID** ($5.7\times$ separation) |
| **H-GEO-13** | **Rewrap residual** | Joining lines and greedily rewrapping severely distorts line count/lengths | Greedy rewrapping closely reconstructs original line count/lengths | **47.1%** | **35.1%** | **23.2%** | **STRONGLY VALID** ($2.0\times$ divergence) |
| **H-GEO-14** | **2D dead-space profile** | Block has persistent vertical blank corridor ($\ge 3$ cols) spanning rows | Text occupancy spans active corridor without persistent vertical blank | **59.5%** | **6.9%** | **26.3%** | **STRONGLY VALID** ($8.6\times$ separation) |
| **H-GEO-15** | **Row independence & grid** | Line boundaries coincide with both vertical seam and syntactic independence | Line boundaries have soft grammatical flow and no vertical seam | **19.3%** | **52.6%** | **34.5%** | **MODERATE** (effective inverted) |
| **H-GEO-16** | **Row-shape autocorrelation** | Numeric token counts or line lengths repeat at short period (lag 2) | Line lengths and token counts vary naturally without repeating rhythm | **39.4%** | **12.2%** | **30.1%** | **MODERATE** ($3.2\times$ vs. prose) |
| **H-GEO-17** | **Stub / value asymmetry** | Left text stub $\to$ Gutter ($\ge 3$ spaces) $\to$ Right numeric/categorical field | Text is distributed as one continuous sentence corridor | **15.9%** | **0.7%** | **2.5%** | **STRONGLY VALID** ($22.7\times$ vs. prose) |
| **H-GEO-18** | **Cell-edge alignment** | Multiple cells align vertically on right or decimal edges across rows | Numeric and punctuation edges occur at arbitrary horizontal offsets | **78.3%** | **6.3%** | **64.4%\*** | **STRONGLY VALID** ($12.4\times$ vs. prose) |

*\*Note on Candidates for H-GEO-10 and H-GEO-18: The candidate pool was originally generated by flagging blocks with `prose_dominant_numeric_alignment`. Consequently, candidates by definition contain accidental numeric alignments, which explains their higher score compared to ordinary prose.*

---

### Detailed Analysis by Hypothesis

#### H-GEO-7: Occupancy Topology (Multi-Run Lines Separated by Gutters)
- **Mechanism**: A line is evaluated for containing $\ge 2$ non-space token runs (length $\ge 2$) separated by an internal gap of $\ge 4$ spaces (a true column gutter).
- **Physical Invariant**: In legacy ASCII, single-column prose uses 1 space between words and 2 spaces for sentence punctuation (`.  The`) or justified spacing. Real tables separate data columns by $\ge 4$ spaces.
- **Empirical Measure**:
  - Tables: **53.5%** of lines contain multi-run topologies.
  - Ordinary Prose: **6.9%**.
  - Candidates: **13.7%**.

#### H-GEO-8: Vertical Seam Coverage (Recurrent Gap Alignment)
- **Mechanism**: Computes column coverage of gaps ($\ge 4$ spaces) across lines to measure whether an empty vertical corridor aligns at the same horizontal column ($\pm 1$).
- **Physical Invariant**: Column gutters in tables align across consecutive rows to establish visual vertical columns.
- **Empirical Measure**:
  - Tables: **75.9%** exhibit a recurrent gap seam across lines.
  - Ordinary Prose: **51.2%** (drops to $< 10\%$ when conditioned on 3-column width).
  - Candidates: **44.0%**.

#### H-GEO-9: Column Character-Class Stability
- **Mechanism**: Calculates the modal probability of character classes (Alpha, Numeric, Punctuation, Space) per column across lines: $\frac{1}{W} \sum_{c=0}^W \max_k P(Class_k \mid c)$.
- **Empirical Finding**: **WEAK** as a global mean ($71.8\%$ tables vs. $74.9\%$ prose), because English prose lines consistently produce letters and spaces in high percentages across lines. It becomes discriminative only when restricted to the middle window (cols 20–60).

#### H-GEO-10: Numeric-Anchor Precision (Positional Clustering)
- **Mechanism**: For blocks with $\ge 3$ numeric values, calculates the fraction of numbers whose right or start edge matches another number's position within $\pm 1$ column.
- **Empirical Measure**:
  - Tables: **23.7%** clustering across all numbers.
  - Ordinary Prose: Only **5.8%**.
  - Candidates: **41.4%** (reflecting the candidate filter selection).

#### H-GEO-11: Row-Template Periodicity (Normalized Token Shapes)
- **Mechanism**: Maps lines to token-type signatures (e.g., `Words -> Num -> Num` or `Words -> Punct -> Num`) and checks if the most frequent row template accounts for $\ge 40\%$ of lines.
- **Empirical Measure**:
  - Tables: **29.6%** exhibit repeating row templates.
  - Ordinary Prose: **15.8%**.
  - Candidates: **19.1%**.

#### H-GEO-12: Indent Transition Grammar (Alternating Row Starts vs. Cell Wraps)
- **Mechanism**: Detects structural alternation in line indentation: base indent ($\le 4$ spaces) alternating with wrapped cell indents ($\ge 10$ spaces) in patterns like $0 \to 12 \to 0 \to 14$.
- **Empirical Measure**:
  - Tables: **6.8%** (high specificity; most table rows are single-line, but wrapped tables exhibit strong alternation).
  - Ordinary Prose: **1.2%**.
  - Candidates: **2.2%**.

#### H-GEO-13: Rewrap Residual (Line Count Divergence Under Greedy Rewrapping)
- **Mechanism**: Concatenates all tokens in the block and greedily rewraps them to the median non-final line width of the source. Computes the normalized line count deviation: $\frac{|\text{Rewrapped Lines} - \text{Source Lines}|}{\text{Source Lines}}$.
- **Physical Invariant**: Continuous hardwrapped prose preserves its line count and shape under greedy rewrapping, whereas tabular records (with short cells and whitespace gaps) are severely distorted when reflowed.
- **Empirical Measure**:
  - Tables: **47.1%** average line count distortion.
  - Ordinary Prose: **35.1%**.
  - Candidates: Only **23.2%** (prose candidate blocks reconstruct their source line counts with minimal residual).

#### H-GEO-14: Two-Dimensional Dead-Space Profile (Persistent Blank Corridors)
- **Mechanism**: Scans the 2D occupancy matrix for a vertical column strip of width $\ge 3$ columns where $\ge 70\%$ of lines are blank spaces within the active text bounding box.
- **Empirical Measure**:
  - Tables: **59.5%** possess a persistent 2D dead-space corridor.
  - Ordinary Prose: **6.9%**.
  - Candidates: **26.3%**.

#### H-GEO-15: Row Independence Conditioned on Geometry
- **Mechanism**: Measures the coincidence of a vertical seam ($\ge 4$ spaces) with syntactic row independence (Line $X$ ends with digit/paren/period and Line $X+1$ starts capitalized).
- **Empirical Measure**:
  - Tables: **19.3%** strict coincidence.
  - Ordinary Prose: **52.6%** lack the vertical seam while showing soft-wrap continuations.

#### H-GEO-16: Row-Shape Autocorrelation (Lag-2 Pattern Periodicity)
- **Mechanism**: Computes lag-2 autocorrelation of numeric token counts per line (detecting 2-line periodic structures: header row $\to$ data row $\to$ header row $\to$ data row).
- **Empirical Measure**:
  - Tables: **39.4%** exhibit lag-2 periodicity.
  - Ordinary Prose: **12.2%**.
  - Candidates: **30.1%**.

#### H-GEO-17: Stub / Value Asymmetry (Text Stub $\to$ Gutter $\to$ Numeric Value)
- **Mechanism**: Detects lines composed of an alphanumeric descriptive stub, followed by a gutter ($\ge 3$ spaces), followed by numeric or currency tokens (`[a-zA-Z]{2,}\s{3,}\$?\d+`).
- **Empirical Measure**:
  - Tables: **15.9%** of lines.
  - Ordinary Prose: **0.7%** of lines ($22.7\times$ separation).
  - Candidates: **2.5%** of lines.

#### H-GEO-18: Cell-Edge Alignment (Right and Decimal Edge Vertical Alignment)
- **Mechanism**: Measures vertical alignment ($\pm 1$ column) of numeric token right edges ($\ge 3$ aligned numbers) or decimal points ($\ge 2$ aligned decimals) across distinct rows.
- **Empirical Measure**:
  - Tables: **78.3%** of blocks have vertically aligned numbers.
  - Ordinary Prose: Only **6.3%** ($12.4\times$ separation).
  - Candidates: **64.4%** (due to baseline candidate filter selection).

---

## 7. Composite Score Validation Benchmark

Evaluated across the full acceptance inventory dataset ($N = 3{,}647$ blocks: $1{,}911$ tables, $1{,}542$ ordinary prose, $194$ reflow candidates):

### Block-Level Composite Evaluation (8 Binary Signals)

| Threshold | Tables ($N=1911$) | Ordinary Prose ($N=1542$) | Reflow Candidates ($N=194$) |
| :--- | :--- | :--- | :--- |
| **Score $\ge 2$** | 26.1% | 81.8% | **97.9%** |
| **Score $\ge 3$** | 13.0% | 71.1% | **93.8%** |
| **Score $\ge 4$** | 6.5% | 51.4% | **86.1%** |
| **Score $\ge 5$** | 3.8% | 32.6% | **71.1%** |

### Double-Newline Passage-Level Evaluation (Exhibits Excluded)

When splitting blocks by double newlines into discrete passages ($N=7{,}307$ pure table passages, $N=1{,}542$ prose, $N=194$ candidates):

| Threshold | Pure Table Passages ($N=7307$) | Ordinary Prose ($N=1542$) | Reflow Candidates ($N=194$) |
| :--- | :--- | :--- | :--- |
| **Score $\ge 3$** | 13.1% | 83.7% | **95.4%** |
| **Score $\ge 4$** | 6.9% | 71.3% | **92.3%** |
| **Score $\ge 5$** | 4.1% | 57.8% | **88.7%** |
| **Score $\ge 6$** | 2.5% | 42.3% | **77.8%** |
