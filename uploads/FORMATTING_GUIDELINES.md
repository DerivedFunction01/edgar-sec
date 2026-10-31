# SEC Form Markdown Formatting Guidelines & Transformation Standard

This document defines the canonical specification for prettifying raw copy-pasted SEC Form text (`uploads/*.txt`) into clean, consistent, and semantically rich GitHub Flavored Markdown (GFM). It serves as the definitive reference for all subagents, manual editors, and validation tools.

---

## 1. Element Selection & Decision Matrix

To ensure clarity, readability, and semantic precision across complex forms (especially **Form 20-F**, **Form 10-K**, **Form 8-K**, and **Form 10-Q**), use the following decision matrix to choose the appropriate Markdown presentation structure:

| Structural Type | Preferred Markdown Construct | When to Use | Examples in 20-F / 10-K / 8-K |
|---|---|---|---|
| **Structured Tabular Data** | **GFM Pipe Table** (`\| Col \| Col \|`) | Standard multi-column disclosures (2–10 columns) with discrete cell values. | • Securities Registered (12b/12g)<br>• Item 16E / 703 Equity Repurchases<br>• Audit Fees by Year (Audit, Tax, etc.)<br>• Board Diversity Matrices |
| **Complex / Multi-Tier Financial Templates** | **Fenced Code Block** (````` ```text `````) | Complex accounting schedules with multi-level nested headers, maturity matrices, or dot leaders (`. . . .`) that break pipe table layout. | • Item 11 Appendix (Interest Rate / Exchange Rate sensitivity models)<br>• Multi-year expected cash flow projections |
| **Literal Formatting & Syntax Examples** | **Fenced Code Block** (````` ```text ````` / ````` ```xml `````) | EDGAR submission headers, XML / Inline XBRL tag specifications, or fixed-width layout mockups where verbatim formatting must be preserved. | • `<SEC-DOCUMENT>` tags<br>• Inline XBRL exhibit descriptors<br>• ASCII signature/filing stamps |
| **Bulleted Prose & Enumerated Clauses** | **Markdown Nested Lists** (`- (a)` / `1.` / `(i)`) | Lettered or numbered provisions that continue a parent sentence or list conditions (NOT section headings). | • List of reportable events under 6-K Item B<br>• Multi-part eligibility conditions under 10-K Instruction I<br>• Items to include under Form 20-F Item 8 |
| **Section Headings** | **Headers** (`#` to `####`) | Document titles, top-level parts, major items, and titled sub-sections. | • `# FORM 20-F`<br>• `## GENERAL INSTRUCTIONS`<br>• `### Item 5. Operating and Financial Review`<br>• `#### (a) Eligible Issuers` (if titled) |
| **Statutory Notes & Instructions** | **Blockquotes** (`> **Note:**`) | Regulatory callouts, statutory rules, warnings, and item instructions. | • `> **Instruction 1 to Item 16F:** ...`<br>• `> **Note to paragraph (2):** ...`<br>• `> **Notice:** ...` |
| **Metadata & Key-Value Fields** | **Bold Key-Value Pairs** (`**Field:** Value`) | Single-line metadata attributes, registrant details, and contact info. | • `**Commission File Number:** 001-XXXXX`<br>• `**Exact name of Registrant:** ...` |
| **Interactive Form Fields** | **GFM Task Lists** (`- [ ]`, `- [x]`) | Checkboxes, radio choices, filing elections, and filer classifications. | • `- [ ] Form 20-F`<br>• `- [ ] Large accelerated filer`<br>• `- [ ] Yes  - [ ] No` |

---

## 2. Rule: Headings vs. Bulleted Prose for `(a)`, `(1)`, `(i)`

In SEC regulatory text, lettered and numbered identifiers (`(a)`, `(1)`, `(i)`) serve two fundamentally different grammatical roles:

### Distinction Rule
1. **Use Heading (`####` or `#####`) ONLY when**:
   - The clause has a distinct title/caption (e.g. `(a) Eligible Issuers.`, `(b) Required Disclosures.`).
   - It represents an independent, major topical subdivision with multiple separate sub-paragraphs.
2. **Use Markdown Lists (`- (a)` / `1.` / `a.` / `(i)`) when**:
   - The clause continues a parent sentence (e.g., `An issuer shall furnish information concerning: (a) changes in business; (b) ...`).
   - It enumerates conditions, exemptions, definitions, or procedural steps.
   - Using a heading would create fragmented 1-line headings that break document flow.

---

### Example A: Bulleted Prose / Enumerated Clauses (Use Lists, NOT Headings)

**Before (Raw Text):**
```text
The information required to be furnished pursuant to (i), (ii) or (iii) above is that which is
material with respect to the issuer and its subsidiaries concerning: changes in business; changes
in management or control; acquisitions or dispositions of assets; bankruptcy or receivership;
changes in registrant’s certifying accountants; the financial condition and results of operations;
material legal proceedings; changes in securities or in the security for registered securities;
defaults upon senior securities; material increases or decreases in the amount outstanding of
securities or indebtedness; the results of the submission of matters to a vote of security holders;
transactions with directors, officers or principal security holders; the granting of options or
payment of other compensation to directors or officers; material cybersecurity incident; and any
other information which the registrant deems of material importance to security holders.
```

**After (Standardized Markdown):**
```markdown
The information required to be furnished pursuant to (i), (ii) or (iii) above is that which is material with respect to the issuer and its subsidiaries concerning:

- Changes in business;
- Changes in management or control;
- Acquisitions or dispositions of assets;
- Bankruptcy or receivership;
- Changes in registrant's certifying accountants;
- The financial condition and results of operations;
- Material legal proceedings;
- Changes in securities or in the security for registered securities;
- Defaults upon senior securities;
- Material increases or decreases in the amount outstanding of securities or indebtedness;
- The results of the submission of matters to a vote of security holders;
- Transactions with directors, officers or principal security holders;
- The granting of options or payment of other compensation to directors or officers;
- Material cybersecurity incidents; and
- Any other information which the registrant deems of material importance to security holders.
```

---

### Example B: Nested Multi-Level Regulatory Conditions (Use Indented Lists)

**Before (Raw Text):**
```text
(1) Conditions for availability of the relief specified in paragraph (2) below:
(a) All of the registrant’s equity securities are owned, either directly or indirectly, by
a single person which is a reporting company under the Act;
(b) During the preceding thirty-six calendar months:
(i) There has not been any material default in the payment of principal, interest, a
sinking or purchase fund installment; and
(ii) There has not been any material default in the payment of rentals under
material long-term leases; and
(c) There is prominently set forth, on the cover page of the Form 10-K, a statement
that the registrant meets the conditions.
```

**After (Standardized Markdown):**
```markdown
#### (1) Conditions for Availability of Relief

Registrants meeting the conditions specified below are entitled to the relief in paragraph (2):

- **(a)** All of the registrant's equity securities are owned, either directly or indirectly, by a single person which is a reporting company under the Act;
- **(b)** During the preceding thirty-six calendar months:
  - **(i)** There has not been any material default in the payment of principal, interest, a sinking or purchase fund installment; and
  - **(ii)** There has not been any material default in the payment of rentals under material long-term leases; and
- **(c)** There is prominently set forth, on the cover page of the Form 10-K, a statement that the registrant meets these conditions.
```

---

## 3. Rule: When to Use Fenced Code Blocks (` ``` `)

Use fenced code blocks (` ```text ` or ` ```xml `) when Markdown tables or paragraphs cannot accurately represent the layout, such as:
1. **Multi-tiered financial schedules** where super-headers, sub-headers, and dot leaders (`. . . .`) collide.
2. **Literal SEC filing examples**, sample forms, and ASCII wireframes.
3. **Machine-readable submission tags** (EDGAR header tags, XML / XBRL syntax).

### Example: Multi-Tier Financial Sensitivity Matrix (Item 11 Appendix)

**Before (Raw Text):**
```text
December 31, 19x1
Expected Maturity Date
19x2 19x3 19x4 19x5 19x6 Thereafter Total Fair Value
Liabilities (US$ Equivalent in millions)
Long-term Debt
Fixed Rate ($US) $XXX $XXX $XXX $XXX $XXX $XXX $XXX $XXX
Average interest rate X.X% X.X% X.X% X.X% X.X% X.X% X.X%
Fixed Rate (DM) XXX XXX XXX XXX XXX XXX XXX XXX
Average interest rate X.X% X.X% X.X% X.X% X.X% X.X% X.X%
```

**After (Standardized Markdown):**
````markdown
#### Interest Rate Sensitivity Table (December 31, 19x1)

```text
===============================================================================================================
                                         Expected Maturity Date
                             ---------------------------------------------------------              Fair
                             19x2    19x3    19x4    19x5    19x6   Thereafter   Total              Value
===============================================================================================================
Liabilities (US$ Equivalent in millions):
Long-term Debt:
  Fixed Rate ($US)           $XXX    $XXX    $XXX    $XXX    $XXX      $XXX       $XXX              $XXX
  Average interest rate      X.X%    X.X%    X.X%    X.X%    X.X%      X.X%       X.X%                -

  Fixed Rate (DM)             XXX     XXX     XXX     XXX     XXX       XXX        XXX               XXX
  Average interest rate      X.X%    X.X%    X.X%    X.X%    X.X%      X.X%       X.X%                -

  Variable Rate ($US)         XXX     XXX     XXX     XXX     XXX       XXX        XXX               XXX
  Average interest rate      X.X%    X.X%    X.X%    X.X%    X.X%      X.X%       X.X%                -
===============================================================================================================
```
````

---

## 4. Rule: Standard Tabular Disclosures (GFM Pipe Tables)

For clean 2-10 column tables with discrete data, use standard GFM pipe tables:

### A. Securities Registered Table (Cover Page)
```markdown
**Securities registered pursuant to Section 12(b) of the Act:**

| Title of Each Class | Trading Symbol(s) | Name of Each Exchange on Which Registered |
| :--- | :--- | :--- |
| Common Stock, $0.01 par value | ABC | New York Stock Exchange |
| 7.50% Senior Notes due 2030 | ABC30 | New York Stock Exchange |
```

### B. Item 16E / Item 703: Purchases of Equity Securities Table
```markdown
| Period | (a) Total Number of Shares Purchased | (b) Average Price Paid per Share | (c) Total Number of Shares Purchased as Part of Publicly Announced Plans or Programs | (d) Maximum Number (or Approximate Dollar Value) of Shares that May Yet Be Purchased Under the Plans or Programs |
| :--- | :---: | :---: | :---: | :---: |
| **Month #1** (Jan 1 – Jan 31) | 100,000 | $50.00 | 100,000 | 900,000 |
| **Month #2** (Feb 1 – Feb 28) | 150,000 | $52.50 | 150,000 | 750,000 |
| **Month #3** (Mar 1 – Mar 31) | 200,000 | $51.00 | 200,000 | 550,000 |
| **Total** | **450,000** | **$51.28** | **450,000** | **550,000** |
```

### C. Item 14 / Item 16C: Principal Accountant Fees & Services Table
```markdown
| Fee Category | Fiscal Year 2024 | Fiscal Year 2023 |
| :--- | ---: | ---: |
| **Audit Fees** | $1,200,000 | $1,100,000 |
| **Audit-Related Fees** | $150,000 | $120,000 |
| **Tax Fees** | $80,000 | $75,000 |
| **All Other Fees** | $20,000 | $15,000 |
| **Total Fees** | **$1,450,000** | **$1,310,000** |
```

---

## 5. Rule: Heading Depths & Sentinel Hierarchy

```markdown
<!-- SENTINEL: <TAG_NAME> -->
# FORM 20-F: <DOCUMENT ROOT TITLE>

<!-- SENTINEL: GENERAL_INSTRUCTIONS -->
## GENERAL INSTRUCTIONS

<!-- SENTINEL: INSTRUCTION_A -->
### A. Who May Use Form 20-F and When It Must be Filed.

#### (a) Eligibility Scope
Text...
```

- **`#` (H1)**: Root document title (one per file).
- **`##` (H2)**: Major structural sections: `## OMB APPROVAL`, `## COVER PAGE`, `## GENERAL INSTRUCTIONS`, `## PART I`, `## PART II`, `## PART III`, `## PART IV`, `## SIGNATURES`, `## INSTRUCTIONS AS TO EXHIBITS`.
- **`###` (H3)**: Specific items or lettered general instructions: `### Item 1. Business`, `### Item 5. Operating and Financial Review and Prospects`, `### A. Rule as to Use of Form 10-K`.
- **`####` (H4)**: Titled sub-items or major numbered sections: `#### (a) Eligible Issuers`, `#### Item 15(a)(1) Financial Statements`.

---

## 6. Rule: Regulatory Notes & Item Instructions (Blockquotes)

Format instructions to items and statutory callouts with GFM blockquotes:

```markdown
> ### Instructions to Item 16F:
> 
> 1. Item 16F applies to all registrants that have had a change in certifying accountant.
> 2. The disclosure called for by this Item should be prepared in accordance with...
```

---

## 7. Rule: Interactive Checkboxes & Filer Categories

Convert ASCII brackets and unicode checkboxes into GFM task lists:

```markdown
Indicate by check mark whether the registrant is a large accelerated filer, an accelerated filer, a non-accelerated filer, or an emerging growth company:

- [ ] Large accelerated filer
- [ ] Accelerated filer
- [ ] Non-accelerated filer
- [ ] Emerging growth company

Indicate by check mark if the registrant is a well-known seasoned issuer:

- [ ] Yes
- [ ] No
```

---

## 8. Rule: Noise Stripping & Paragraph Reflow

1. **Delete Running Headers & Footers**:
   - `2 of 40`, `15 of 105`, `Page 12 of 19`
   - Repeated `Board of Governors of the Federal Reserve System OMB Number 7100-0091 Approval expires February 28, 2027`
   - Redundant mid-document Paperwork Reduction Act disclaimers (keep only the top OMB approval block).
2. **Unwrap Hard Line Breaks**:
   - Join sentences broken across lines by 80-character terminal wraps into clean, flowing Markdown paragraphs separated by a blank line (`\n\n`).

---

## 9. Rule: Context & Adjacent Partitions (Read-Only Hints)

When working on an isolated slice:
- **Read-Only Inspection**: You are encouraged to view the preceding or succeeding partitions (e.g. `../03_.../raw.txt` or `../03_.../formatted.md`) to understand parent hierarchy, list indentation levels, table continuity, or surrounding context.
- **Strict Boundary Scope**: Never edit or write outside your assigned partition directory. Use other partitions strictly as read-only reference hints.

---

## 10. Subagent & Worker Verification Checklist

- [ ] **No Content Loss**: Verify every sentence and citation from `raw.txt` exists in `formatted.md`.
- [ ] **Bulleted Prose vs Headings**: Ensure `(a)`, `(1)`, `(i)` clauses that are continuing sentences or lists of conditions are formatted as nested lists (`- **(a)** ...`), not headings.
- [ ] **Fenced Code Blocks**: Literal format examples, XML/XBRL tags, and multi-tiered financial models use fenced ```` ```text ```` blocks.
- [ ] **GFM Tables**: Standard multi-column tabular data uses `| col | col |` format.
- [ ] **Sentinel Preserved**: Exact `<!-- SENTINEL: ... -->` comments are retained at the start of each section.
- [ ] **No Page Numbers**: Strings like `N of M` and Federal Reserve headers are completely removed.
- [ ] **Blockquotes**: All `Instructions:`, `Note:`, and `Caution:` callouts use `> **Note:** ...`.
- [ ] **Checkboxes**: Checkboxes use `- [ ]` syntax.
- [ ] **Context Verification**: If continuing a list or sentence from a previous slice, verify indentation level aligns with the preceding slice.

