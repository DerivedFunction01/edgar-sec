# SEC EDGAR Tag-Free Exhibit Classification Handbook: Tiers 1, 2, and 3
**Item 601 of Regulation S-K (17 CFR § 229.601)**
*Complete Operational Heuristic Specifications for NLP and Tag-Free Document Parsing*

---

## Executive Overview & Methodological Framework

### 1. Purpose and Operational Objective
Under 17 CFR § 229.601 (Item 601 of Regulation S-K), exhibits filed with the U.S. Securities and Exchange Commission (SEC) across periodic reports (Form 10-K, Form 10-Q, Form 8-K) and registration statements (Form S-1, Form S-3, Form S-4, Form SF-3) vary widely in frequency, structural design, and statutory intent. 

Automated processing pipelines often ingest filings after stripping HTML tags, XML tags, CSS styles, and SGML wrappers (using libraries such as BeautifulSoup or lxml). Traditional document classifiers that rely on HTML markup or metadata tags fail when processing tag-free prose.

This handbook establishes invariant, plain-text-only prose heuristics—anchors, syntactic headers, statutory citations, and negative lookahead rules—targeting the initial document header (lines 1 to 25, or first 1,500 characters) to classify every Item 601 exhibit without tag dependency.

While a fast hueristic is to specifically look for `(?:ex(?:-|\s+)|exhibit\s+)[0-9]+\.?[0-9]?`; not all prose may contain this easy identifier.

### 2. Market Prevalence Tiering Structure
The 601 exhibit taxonomy is segmented into three distinct operational tiers:
- **Tier 1: High Prevalence (Core Periodic & Registration Filings)**: Universally mandated exhibits appearing in routine periodic reports and registration statements (covering >80% of corporate exhibits filed on EDGAR). Includes Articles of Incorporation (3.1), Bylaws (3.2), Securities Descriptions & Indentures (4), Material Contracts (10), Subsidiaries (21), Consents (23), Powers of Attorney (24), SOX 302 Certifications (31.1), SOX 906 Certifications (32.1), and Interactive Data Files (101, 104).
- **Tier 2: Medium Prevalence (Transaction-Specific, Governance, & Event-Driven Filings)**: Common event-driven exhibits filed upon specific corporate transactions, auditor transitions, governance updates, and financing events. Includes Underwriting Agreements (1), Plans of Acquisition/Merger (2), Opinions of Counsel (5, 8), Codes of Ethics (14), Auditor Letters (15, 16, 18), Director Departures (17), Insider Trading Policies (19), Subsidiary Guarantors (22), Trustee Eligibility (25), Clawback Policies (97), Press Releases/Additional Exhibits (99), and Filing Fee Tables (107).
- **Tier 3: Low Prevalence & Specialized Domain Filings**: Highly specialized exhibits restricted to specific registrant categories such as asset-backed securitizations (ABS), mining operations under Subpart 1300, de-SPAC business combinations, and specialty trusts. Includes Voting Trusts (9), Shareholder Reports (13), Unitholder Statements (20), ABS SOX Certifications (31.ii), Servicing Compliance and Attestation Reports (33, 34, 35), Shelf ABS Certifications (36), Mine Safety Disclosures (95), Mining Technical Report Summaries (96), de-SPAC Opinions/Appraisals (98), ABS Asset Data & Documentation (102, 103), and Static Pool Data (106).
- **Reserved / Obsolete Exhibits**: Exhibits (6), (11)–(12), (26)–(30), (37)–(94), (100), and (105) are reserved or obsolete.

---

## PART I: TIER 1 — HIGH PREVALENCE (CORE PERIODIC & REGISTRATION FILINGS)

### Tier 1 Overview Table

| Exhibit ID | Exhibit Title (Item 601) | Validated Link Count | Top Line Range | Primary Detection Prose Keywords | Secondary Disambiguation Tokens |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **EX-3.1** | Articles of Incorporation | 4 | Lines 1–10 | `CERTIFICATE OF INCORPORATION`, `ARTICLES OF INCORPORATION`, `CERTIFICATE OF FORMATION`, `CHARTER` | `RESTATED`, `AMENDED AND RESTATED`, `DELAWARE GENERAL CORPORATION LAW`, `SECRETARY OF STATE`, `CORPORATE NAME` |
| **EX-3.2** | Bylaws | 4 | Lines 1–8 | `BYLAWS`, `BY-LAWS`, `AMENDED AND RESTATED BYLAWS` | `ARTICLE I`, `OFFICES`, `MEETINGS OF STOCKHOLDERS`, `BOARD OF DIRECTORS` (must NOT match "Certificate of Incorporation") |
| **EX-4** | Instruments Defining Rights of Security Holders & Securities Description | 4 | Lines 1–12 | `INDENTURE`, `DESCRIPTION OF THE REGISTRANT'S SECURITIES`, `DESCRIPTION OF CAPITAL STOCK`, `REGISTERED PURSUANT TO SECTION 12` | `TRUSTEE`, `SUPPLEMENTAL INDENTURE`, `SENIOR NOTES`, `COMMON STOCK`, `PURSUANT TO SECTION 12 OF THE SECURITIES EXCHANGE ACT OF 1934` |
| **EX-10** | Material Contracts | 4 | Lines 1–12 | `CREDIT AGREEMENT`, `LOAN AGREEMENT`, `EMPLOYMENT AGREEMENT`, `SEPARATION AGREEMENT`, `STOCK OPTION PLAN`, `COMMERCIAL CONTRACT` | `ADMINISTRATIVE AGENT`, `LENDERS`, `BORROWER`, `EXECUTIVE`, `TERM LOAN`, `BASE SALARY` (distinguish from EX-4 indentures and EX-2 plans) |
| **EX-21** | Subsidiaries of the Registrant | 4 | Lines 1–8 | `SUBSIDIARIES OF`, `SIGNIFICANT SUBSIDIARIES`, `LIST OF SUBSIDIARIES`, `SUBSIDIARIES OF THE REGISTRANT` | `JURISDICTION OF INCORPORATION`, `PERCENTAGE OF OWNERSHIP`, `STATE OR JURISDICTION OF ORGANIZATION` |
| **EX-23** | Consents of Experts and Counsel | 4 | Lines 1–6 | `CONSENT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM`, `CONSENT OF INDEPENDENT AUDITORS`, `CONSENT OF COUNSEL` | `WE CONSENT TO THE INCORPORATION BY REFERENCE`, `FORM S-3`, `FORM S-8`, `ANNUAL REPORT ON FORM 10-K`, `REPORT OF INDEPENDENT` |
| **EX-24** | Power of Attorney | 4 | Lines 1–8 | `POWER OF ATTORNEY`, `SPECIAL POWER OF ATTORNEY`, `LIMITED POWER OF ATTORNEY` | `KNOW ALL BY THESE PRESENTS`, `CONSTITUTES AND APPOINTS`, `ATTORNEY-IN-FACT`, `SIGNING SINGLY`, `SECTION 16`, `FORM ID`, `EDGAR NEXT` |
| **EX-31.1** | Rule 13a-14(a)/15d-14(a) Certifications (SOX 302) | 4 | Lines 1–10 | `CERTIFICATION OF CHIEF EXECUTIVE OFFICER`, `CERTIFICATION PURSUANT TO RULE 13A-14(A)`, `CERTIFICATION PURSUANT TO SECTION 302` | `I, [Name], certify that:`, `1. I have reviewed this`, `2. Based on my knowledge, this report does not contain any untrue statement of a material fact`, `internal control over financial reporting` |
| **EX-32.1** | Section 1350 Certifications (SOX 906) | 4 | Lines 1–10 | `CERTIFICATION PURSUANT TO 18 U.S.C. SECTION 1350`, `CERTIFICATION PURSUANT TO SECTION 906 OF THE SARBANES-OXLEY ACT OF 2002` | `18 U.S.C. SECTION 1350`, `SECTION 906`, `ACCOMPANIES THE REPORT`, `FAIRLY PRESENTS, IN ALL MATERIAL RESPECTS`, `IS BEING FURNISHED SOLELY PURSUANT TO` |
| **EX-101** | Interactive Data File (Inline XBRL) | 4 | Lines 1–5 | `<?xml`, `<schema`, `<linkbase`, `EX-101.INS`, `EX-101.SCH`, `EX-101.CAL`, `EX-101.DEF`, `EX-101.LAB`, `EX-101.PRE` | `xmlns:xbrli=`, `http://www.xbrl.org/`, `IXBRL Taxonomy Extension`, `Inline XBRL Instance Document` |
| **EX-104** | Cover Page Interactive Data File | 4 | Lines 1–15 | `Cover Page Interactive Data File`, `EX-104` | `formatted as Inline XBRL and contained in Exhibit 101`, `the cover page XBRL tags are embedded within the Inline XBRL document`, `Rule 406 of Regulation S-T` |

---

### Tier 1 Deep-Dive Profiles

#### EX-3.1 — Articles of Incorporation
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(3)(i)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Schering-Plough Corporation` (SIC 2834 — Pharmaceutical Preparations; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/310158/000095012309009217/y77207exv3w1wb.htm](https://www.sec.gov/Archives/edgar/data/310158/000095012309009217/y77207exv3w1wb.htm) / Accession: `0000950123-09-009217`
  2. `KLA Corporation` (SIC 3674 — Semiconductors & Related Devices; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/319201/000119312526269375/d144278dex31.htm](https://www.sec.gov/Archives/edgar/data/319201/000119312526269375/d144278dex31.htm) / Accession: `0001193125-26-269375`
  3. `CoreWeave, Inc.` (SIC 7374 — Computer Processing & Data Preparation; Non-Accelerated / IPO) — [https://www.sec.gov/Archives/edgar/data/1769628/000119312525085800/d935353dex31.htm](https://www.sec.gov/Archives/edgar/data/1769628/000119312525085800/d935353dex31.htm) / Accession: `0001193125-25-085800`
  4. `The ODP Corporation` (SIC 5940 — Retail Stores; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/800240/000119312520184552/d45006dex31.htm](https://www.sec.gov/Archives/edgar/data/800240/000119312520184552/d45006dex31.htm) / Accession: `0001193125-20-184552`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 3.1
AMENDED AND RESTATED CERTIFICATE OF INCORPORATION
OF
THE ODP CORPORATION
The present name of the corporation is The ODP Corporation (the “Corporation”).
The Corporation was incorporated under the name “Office Depot, Inc.” by the filing
of its original Certificate of Incorporation with the Secretary of State of the
State of Delaware on February 28, 1986.
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:AMENDED\s+AND\s+RESTATED\s+|RESTATED\s+|SECOND\s+AMENDED\s+AND\s+RESTATED\s+)?(?:CERTIFICATE|ARTICLES)\s+OF\s+(?:INCORPORATION|FORMATION|ORGANIZATION) `
  - Disambiguation Rule: Must contain `CERTIFICATE OF INCORPORATION` or `ARTICLES OF INCORPORATION` within the first 10 lines, and must **not** match `BYLAWS` or `BY-LAWS` in the main structural title.
  - Suggested Regex / Logic:
```python
re.compile(
    r"^(?=.*? (?:CERTIFICATE|ARTICLES)\s+OF\s+(?:INCORPORATION|FORMATION|ORGANIZATION) )(?!.*? BY[- ]?LAWS )",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Exhibits describing securities under EX-4 or merger agreements under EX-2 that quote the certificate of incorporation in recitals.
  - Mitigation: Restrict match strictly to the top 10 lines or require the title to be preceded only by an optional exhibit indicator (e.g., `Exhibit 3.1`). Add negative lookahead for `AGREEMENT AND PLAN OF MERGER`.

---

#### EX-3.2 — Bylaws
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(3)(ii)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Matterport, Inc.` (SIC 7372 — Prepackaged Software; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1819394/000119312521227538/d206094dex32.htm](https://www.sec.gov/Archives/edgar/data/1819394/000119312521227538/d206094dex32.htm) / Accession: `0001193125-21-227538`
  2. `Vical Incorporated` (SIC 2836 — Biological Products; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/819050/000119312510180957/dex32.htm](https://www.sec.gov/Archives/edgar/data/819050/000119312510180957/dex32.htm) / Accession: `0001193125-10-180957`
  3. `Circle Internet Group, Inc.` (SIC 6200 — Security & Commodity Services; Large Accelerated / IPO) — [https://www.sec.gov/Archives/edgar/data/1876042/000119312525070481/d737521dex32.htm](https://www.sec.gov/Archives/edgar/data/1876042/000119312525070481/d737521dex32.htm) / Accession: `0001193125-25-070481`
  4. `The Pennant Group, Inc.` (SIC 8082 — Home Health Care Services; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1766400/000119312519260914/d812063dex32.htm](https://www.sec.gov/Archives/edgar/data/1766400/000119312519260914/d812063dex32.htm) / Accession: `0001193125-19-260914`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 3.2
AMENDED AND RESTATED BYLAWS
OF
MATTERPORT, INC.
ARTICLE I
OFFICES
Section 1.1. Registered Office. The registered office of Matterport, Inc. (the “Corporation”)
in the State of Delaware shall be established and maintained at...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:AMENDED\s+AND\s+RESTATED\s+|SECOND\s+AMENDED\s+AND\s+RESTATED\s+)?BY[- ]?LAWS `
  - Disambiguation Rule: The title token `BYLAWS` appears on a dedicated title line in lines 1–8; subsequent lines (lines 4–20) introduce internal governance subdivisions (`ARTICLE I`, `OFFICES`, `MEETINGS OF STOCKHOLDERS`).
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+3\.2\s+)?(?:AMENDED\s+(?:AND\s+RESTATED\s+)?)?BY[- ]?LAWS(?:\s+OF\s+[\w\s.,]+)?$",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Board resolutions amending a single section of the bylaws filed under Form 8-K or EX-99.
  - Mitigation: Ensure lines 1–15 do not contain `CURRENT REPORT` or `ITEM 5.03`. Enforce presence of organizational article headers (`ARTICLE I` or `Section 1`).

---

#### EX-4 — Instruments Defining Rights of Security Holders & Securities Description
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(4)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `McCormick & Company, Inc.` (SIC 2090 — Food & Kindred Products; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/63754/000006375422000005/mkc-11302021xex4xiiidescri.htm](https://www.sec.gov/Archives/edgar/data/63754/000006375422000005/mkc-11302021xex4xiiidescri.htm) / Accession: `0000063754-22-000005`
  2. `Snap Inc.` (SIC 7370 — Computer Services; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1564408/000119312519218034/d772327dex41.htm](https://www.sec.gov/Archives/edgar/data/1564408/000119312519218034/d772327dex41.htm) / Accession: `0001193125-19-218034`
  3. `Sprouts Farmers Market, Inc.` (SIC 5411 — Grocery Stores; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1575515/000095017023005723/sfm-ex4_1.htm](https://www.sec.gov/Archives/edgar/data/1575515/000095017023005723/sfm-ex4_1.htm) / Accession: `0000950170-23-005723`
  4. `SBA Communications Corp` (SIC 6798 — Real Estate Investment Trusts; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1034054/000119312526315142/d130705dex41.htm](https://www.sec.gov/Archives/edgar/data/1034054/000119312526315142/d130705dex41.htm) / Accession: `0001193125-26-315142`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 4(xiii)
DESCRIPTION OF THE REGISTRANT'S SECURITIES
REGISTERED PURSUANT TO SECTION 12 OF THE
SECURITIES EXCHANGE ACT OF 1934
As of January 27, 2022, McCormick & Company, Incorporated (the "Corporation" or "Registrant")
has two classes of securities registered under Section 12 of the Securities Exchange Act of 1934...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:DESCRIPTION\s+OF\s+(?:THE\s+)?REGISTRANT['’]?S\s+SECURITIES|(?:SENIOR\s+|SUBORDINATED\s+)?INDENTURE) `
  - Disambiguation Rule: Securities Description branch disambiguated by `REGISTERED PURSUANT TO SECTION 12 OF THE SECURITIES EXCHANGE ACT OF 1934`. Debt Indenture branch disambiguated by identifying a `Trustee` (e.g., `as Trustee`, `THE BANK OF NEW YORK MELLON`, `U.S. BANK`) paired with `Senior Notes due` or `Trust Indenture Act`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:DESCRIPTION\s+OF\s+(?:THE\s+)?REGISTRANT['’]?S\s+SECURITIES|"
    r"(?:SENIOR\s+|SUBORDINATED\s+)?INDENTURE[\s\S]{1,250}? as\s+Trustee )",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: EX-10 Credit Agreements that mention indentures in debt incurrence covenants.
  - Mitigation: Credit agreements feature `Administrative Agent` and `Borrower`; EX-4 debt instruments feature `Trustee`, `Issuer`, and `Securities Registrar`.

---

#### EX-10 — Material Contracts
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(10)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Vantage Drilling International` (SIC 1381 — Drilling Oil & Gas Wells; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/1465872/000095017023015741/ck0001465872-ex10_16.htm](https://www.sec.gov/Archives/edgar/data/1465872/000095017023015741/ck0001465872-ex10_16.htm) / Accession: `0000950170-23-015741`
  2. `TripAdvisor, Inc.` (SIC 7374 — Computer Processing & Data Preparation; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1526520/000095017023017169/trip-ex10_1.htm](https://www.sec.gov/Archives/edgar/data/1526520/000095017023017169/trip-ex10_1.htm) / Accession: `0000950170-23-017169`
  3. `Graphic Packaging International` (SIC 2650 — Paperboard Containers; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1792781/000119312521184502/d895088dex101.htm](https://www.sec.gov/Archives/edgar/data/1792781/000119312521184502/d895088dex101.htm) / Accession: `0001193125-21-184502`
  4. `Clean Harbors, Inc.` (SIC 4955 — Hazardous Waste Management; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/768835/000095015203010297/l04459aexv10.htm](https://www.sec.gov/Archives/edgar/data/768835/000095015203010297/l04459aexv10.htm) / Accession: `0000950152-03-010297`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 10.16
EMPLOYMENT AGREEMENT
THIS EMPLOYMENT AGREEMENT (this “Agreement”) is entered into between Vantage Drilling International
(the “Company”) and Douglas E. Stewart (“Executive”), effective as of March 1, 2023.
WHEREAS, the Company desires to employ Executive, and Executive desires to accept such employment,
on the terms and conditions set forth herein;
NOW, THEREFORE, in consideration of the mutual covenants herein contained...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:CREDIT\s+AGREEMENT|TERM\s+LOAN\s+AGREEMENT|CREDIT\s+FACILITY|EMPLOYMENT\s+AGREEMENT|RESTRICTED\s+STOCK\s+UNIT\s+AGREEMENT|LEASE\s+AGREEMENT|SEVERANCE\s+AGREEMENT|SERVICES\s+AGREEMENT) `
  - Disambiguation Rule: Opening recitals: `THIS [AGREEMENT] is entered into as of... by and between...` paired with operational/compensatory counterparties (`Borrower`, `Administrative Agent`, `Lenders`, `Company`, `Executive`, `Employee`).
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+10[\w.]*\s+)?[\w\s,–—-]+?(?:AGREEMENT|PLAN|LEASE)\s*
[\s\S]{1,500}?"
    r"(?:entered\s+into\s+by\s+and\s+between|among\s+[\w\s,]+as\s+(?:Borrower|Administrative\s+Agent|Lenders|Company|Executive)|WITNESSETH)",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Underwriting agreements (EX-1) or Merger plans (EX-2).
  - Mitigation: Add negative lookahead for `UNDERWRITING AGREEMENT` and `AGREEMENT AND PLAN OF MERGER`.

---

#### EX-21 — Subsidiaries of the Registrant
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(21)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `The Goldman Sachs Group, Inc.` (SIC 6211 — Security Brokers & Dealers; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/886982/000119312521049380/d39654dex211.htm](https://www.sec.gov/Archives/edgar/data/886982/000119312521049380/d39654dex211.htm) / Accession: `0001193125-21-049380`
  2. `IntercontinentalExchange, Inc.` (SIC 6200 — Security & Commodity Exchanges; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1174746/000095014407001603/g05422exv21w1.htm](https://www.sec.gov/Archives/edgar/data/1174746/000095014407001603/g05422exv21w1.htm) / Accession: `0000950144-07-001603`
  3. `Square, Inc. (Block, Inc.)` (SIC 7389 — Business Services; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1512673/000119312515343733/d937622dex211.htm](https://www.sec.gov/Archives/edgar/data/1512673/000119312515343733/d937622dex211.htm) / Accession: `0001193125-15-343733`
  4. `EnergySolutions, Inc.` (SIC 4955 — Hazardous Waste Management; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1393744/000139374414000008/ex-211subsidiarylist.htm](https://www.sec.gov/Archives/edgar/data/1393744/000139374414000008/ex-211subsidiarylist.htm) / Accession: `0001393744-14-000008`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EXHIBIT 21.1
Significant Subsidiaries of the Registrant
The following are significant subsidiaries of The Goldman Sachs Group, Inc. as of December 31, 2020
and the states or jurisdictions in which they are organized. Indentation indicates that the
subsidiary is owned by the entity above it.
Name of Subsidiary | State or Jurisdiction of Organization
Goldman Sachs & Co. LLC | New York
Goldman Sachs Bank USA | New York
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:SIGNIFICANT\s+)?SUBSIDIARIES\s+OF\s+(?:THE\s+)?(?:REGISTRANT|COMPANY|[\w\s.,]+) ` OR `(?i) LIST\s+OF\s+SUBSIDIARIES `
  - Disambiguation Rule: Header introduces subsidiary entities; lines 3–15 contain tabular columns: `Name of Subsidiary` and `State or Jurisdiction of Organization` / `Jurisdiction of Incorporation`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:SUBSIDIARIES\s+OF\s+(?:THE\s+)?(?:REGISTRANT|COMPANY)|LIST\s+OF\s+(?:SIGNIFICANT\s+)?SUBSIDIARIES)[\s\S]{1,400}?"
    r"(?:Jurisdiction|State|Country)\s+of\s+(?:Incorporation|Organization)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: EX-22 Subsidiary Guarantor schedules.
  - Mitigation: EX-22 explicitly details debt instruments and guarantee statuses (`Guarantors of Debt Securities`). EX-21 strictly tabulates corporate entities and incorporation jurisdictions.

---

#### EX-23 — Consents of Experts and Counsel
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(23)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `The ODP Corporation` (SIC 5940 — Retail Stores; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/800240/000095014405002321/g93309exv23w1.htm](https://www.sec.gov/Archives/edgar/data/800240/000095014405002321/g93309exv23w1.htm) / Accession: `0000950144-05-002321`
  2. `Erasca, Inc.` (SIC 2834 — Pharmaceutical Preparations; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1761918/000119312526104150/eras-ex23_1.htm](https://www.sec.gov/Archives/edgar/data/1761918/000119312526104150/eras-ex23_1.htm) / Accession: `0001193125-26-104150`
  3. `UiPath, Inc.` (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1734722/000173472226000012/path-2026131xconsentxkpmg.htm](https://www.sec.gov/Archives/edgar/data/1734722/000173472226000012/path-2026131xconsentxkpmg.htm) / Accession: `0001734722-26-000012`
  4. `Circle Internet Group, Inc.` (SIC 6200 — Commodity & Security Dealers; Large Accelerated / IPO) — [https://www.sec.gov/Archives/edgar/data/1876042/000119312526335377/d149697dex231.htm](https://www.sec.gov/Archives/edgar/data/1876042/000119312526335377/d149697dex231.htm) / Accession: `0001193125-26-335377`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 23.1
CONSENT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM
We consent to the incorporation by reference in this Registration Statement on Form S-3
of our report dated March 9, 2026 relating to the financial statements of Circle Internet Group, Inc.,
appearing in the Annual Report on Form 10-K for the year ended December 31, 2025.
We also consent to the reference to us under the heading “Experts” in such Registration Statement.
/s/ Deloitte & Touche LLP
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) CONSENT\s+OF\s+(?:INDEPENDENT\s+(?:REGISTERED\s+PUBLIC\s+ACCOUNTING\s+FIRM|AUDITORS?)|COUNSEL|LEGAL\s+COUNSEL) `
  - Disambiguation Rule: Invariant operative sentence: `We consent to the (?:incorporation by reference|use) of our report` within lines 1–6.
  - Suggested Regex / Logic:
```python
re.compile(
    r"CONSENT\s+OF\s+INDEPENDENT\s+(?:REGISTERED\s+PUBLIC\s+ACCOUNTING\s+FIRM|AUDITORS?)"
    r"[\s\S]{1,250}? (?:We\s+consent\s+to\s+the\s+(?:incorporation\s+by\s+reference|use)) ",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Full audit reports inside Form 10-K Item 8.
  - Mitigation: Audit reports state `Opinion on the Financial Statements`. Consents state `Consent of...` and `We consent to...`.

---

#### EX-24 — Power of Attorney
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(24)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Workspace Property Trust` (SIC 6798 — Real Estate Investment Trusts; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/789460/000095017025058304/wkc-ex24_poa.htm](https://www.sec.gov/Archives/edgar/data/789460/000095017025058304/wkc-ex24_poa.htm) / Accession: `0000950170-25-058304`
  2. `Camden Property Trust` (SIC 6798 — Real Estate Investment Trusts; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1020941/000095017025000402/cpt-ex24.htm](https://www.sec.gov/Archives/edgar/data/1020941/000095017025000402/cpt-ex24.htm) / Accession: `0000950170-25-000402`
  3. `Intellia Therapeutics, Inc.` (SIC 2836 — Biological Products; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1914448/000095017025002115/ntla-ex24_poa.htm](https://www.sec.gov/Archives/edgar/data/1914448/000095017025002115/ntla-ex24_poa.htm) / Accession: `0000950170-25-002115`
  4. `Assurant, Inc.` (SIC 6331 — Insurance; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/2087084/000119312526114357/aiz-ex24_docx.htm](https://www.sec.gov/Archives/edgar/data/2087084/000119312526114357/aiz-ex24_docx.htm) / Accession: `0001193125-26-114357`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 24
POWER OF ATTORNEY
Know all by these presents that the undersigned hereby constitutes and appoints
each of Scott Giacobello and Jane Doe, signing singly, the undersigned's true and
lawful attorney-in-fact to:
(1) execute for and on behalf of the undersigned Forms 3, 4, and 5 in accordance
with Section 16(a) of the Securities Exchange Act of 1934...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:LIMITED\s+|SPECIAL\s+)?POWER\s+OF\s+ATTORNEY `
  - Disambiguation Rule: Lines 2–10 contain opening grant language: `KNOW ALL (?:MEN\s+)?BY\s+THESE\s+PRESENTS` and `constitutes\s+and\s+appoints[\s\S]{1,100}?attorney-in-fact`.
  - Suggested Regex / Logic:
```python
re.compile(
    r" POWER\s+OF\s+ATTORNEY [\s\S]{1,350}?"
    r"(?:constitutes?\s+and\s+appoints?|true\s+and\s+lawful\s+attorney[- ]in[- ]fact|Know\s+all\s+(?:men\s+)?by\s+these\s+presents)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Powers of attorney embedded inside signature pages of a registration statement.
  - Mitigation: Document header must open with the primary title `POWER OF ATTORNEY`.

---

#### EX-31.1 — Rule 13a-14(a)/15d-14(a) Certifications (SOX 302)
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(31)(i)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Apple Inc.` (SIC 3571 — Electronic Computers; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/320193/000119312512444068/d411355dex311.htm](https://www.sec.gov/Archives/edgar/data/320193/000119312512444068/d411355dex311.htm) / Accession: `0001193125-12-444068`
  2. `PennantPark Floating Rate Capital Ltd.` (SIC 6221 — Commodity Contracts & Funds; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1504619/000119312526342352/pflt-ex31_1.htm](https://www.sec.gov/Archives/edgar/data/1504619/000119312526342352/pflt-ex31_1.htm) / Accession: `0001193125-26-342352`
  3. `Stark Novus Financial Inc.` (SIC 6162 — Mortgage Bankers; Smaller Reporting) — [https://www.sec.gov/Archives/edgar/data/1759546/000149315226038484/ex31-1.htm](https://www.sec.gov/Archives/edgar/data/1759546/000149315226038484/ex31-1.htm) / Accession: `0001493152-26-038484`
  4. `Quarta-Rad, Inc.` (SIC 3829 — Measuring Devices; Smaller Reporting) — [https://www.sec.gov/Archives/edgar/data/1549631/000149315222025893/ex31-1.htm](https://www.sec.gov/Archives/edgar/data/1549631/000149315222025893/ex31-1.htm) / Accession: `0001493152-22-025893`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 31.1
CERTIFICATION
I, Timothy D. Cook, certify that:
1. I have reviewed this annual report on Form 10-K of Apple Inc.;
2. Based on my knowledge, this report does not contain any untrue statement of a material fact
or omit to state a material fact necessary to make the statements made, in light of the
circumstances under which such statements were made, not misleading with respect to the period
covered by this report;
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) I,\s*[^,
]+,\s*certify\s+that:\s*
\s*1\.\s*I\s+have\s+reviewed\s+this `
  - Disambiguation Rule: Invariant Item 601(b)(31) mandatory statutory recitation: contains numbered list where point 1 is `I have reviewed this [report]` and point 2 is `Based on my knowledge, this report does not contain any untrue statement`. Differentiated from EX-32 because EX-31 contains 5 numbered paragraphs and mentions `disclosure controls and procedures` and `internal control over financial reporting`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"I,\s*[^,
]+,\s*certify\s+that:\s*1\.\s*I\s+have\s+reviewed\s+this\s+(?:annual|quarterly)?\s*report"
    r"[\s\S]{1,350}?2\.\s*Based\s+on\s+my\s+knowledge,\s*this\s+report\s+does\s+not\s+contain\s+any\s+untrue\s+statement",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Asset-backed certifications under EX-31(ii) which review Form 10-D and Item 1123 of Regulation AB.
  - Mitigation: For standard corporate filers (EX-31(i)), point 4 references `Exchange Act Rules 13a-15(e) and 15d-15(e)`. Negative lookahead on `Item 1123 of Regulation AB` isolates EX-31.1 from EX-31(ii).

---

#### EX-32.1 — Section 1350 Certifications (SOX 906)
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(32)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Microsoft Corporation` (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-ex32_1.htm](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-ex32_1.htm) / Accession: `0001193125-26-323660`
  2. `HPS Net Lease Income REIT` (SIC 6798 — Real Estate Investment Trusts; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/2107762/000119312526328846/d327808dex321.htm](https://www.sec.gov/Archives/edgar/data/2107762/000119312526328846/d327808dex321.htm) / Accession: `0001193125-26-328846`
  3. `Altimeter Growth Corp. 2` (SIC 6770 — Blank Checks; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/1830232/000119312521328847/d211333dex321.htm](https://www.sec.gov/Archives/edgar/data/1830232/000119312521328847/d211333dex321.htm) / Accession: `0001193125-21-328847`
  4. `Invesco Galaxy Bitcoin ETF` (SIC 6221 — Commodity Contracts Brokers & Dealers; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/2086438/000119312526316158/ck0002086438-ex32_1.htm](https://www.sec.gov/Archives/edgar/data/2086438/000119312526316158/ck0002086438-ex32_1.htm) / Accession: `0001193125-26-316158`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 32.1
CERTIFICATION PURSUANT TO
18 U.S.C. SECTION 1350,
AS ADOPTED PURSUANT TO
SECTION 906 OF THE SARBANES-OXLEY ACT OF 2002
In connection with the Annual Report of Microsoft Corporation on Form 10-K for the period
ended June 30, 2026 as filed with the Securities and Exchange Commission on the date hereof...
I, Satya Nadella, Chief Executive Officer of the Company, certify, pursuant to 18 U.S.C. Section 1350...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:18\s+U\.?S\.?C\.?\s+(?:SECTION\s+)?1350|SECTION\s+906\s+OF\s+THE\s+SARBANES[- ]OXLEY\s+ACT\s+OF\s+2002) `
  - Disambiguation Rule: Invariant two-prong certification: (1) `fully complies with the requirements of section 13(a) or 15(d)` and (2) `information contained in the [Report] fairly presents, in all material respects, the financial condition`. Does not contain the 5 numbered paragraphs of SOX 302.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:18\s+U\.?S\.?C\.?\s*(?:§|Section)?\s*1350|Section\s+906)[\s\S]{1,500}?"
    r"(?:fully\s+complies\s+with\s+the\s+requirements\s+of\s+section\s+13\(a\)|fairly\s+presents,\s+in\s+all\s+material\s+respects)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Footnote references in 10-K Item 15 index mentioning certifications furnished pursuant to Section 906.
  - Mitigation: Ensure text contains affirmative operative certification language `certify, pursuant to 18 U.S.C. Section 1350` or `does hereby certify`.

---

#### EX-101 — Interactive Data File (Inline XBRL)
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(101)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `DocuSign, Inc.` (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1261333/000126133326000074/0001261333-26-000074-index.htm](https://www.sec.gov/Archives/edgar/data/1261333/000126133326000074/0001261333-26-000074-index.htm) / Accession: `0001261333-26-000074`
  2. `Stratasys Ltd.` (SIC 3577 — Computer Storage Equipment; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1517396/000162828025023630/0001628280-25-023630-index.htm](https://www.sec.gov/Archives/edgar/data/1517396/000162828025023630/0001628280-25-023630-index.htm) / Accession: `0001628280-25-023630`
  3. `Exicure, Inc.` (SIC 2834 — Pharmaceutical Preparations; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1698530/000169853018000044/0001698530-18-000044-index.htm](https://www.sec.gov/Archives/edgar/data/1698530/000169853018000044/0001698530-18-000044-index.htm) / Accession: `0001698530-18-000044`
  4. `DecisionPoint Systems, Inc.` (SIC 7373 — Computer Systems Design; Smaller Reporting) — [https://www.sec.gov/Archives/edgar/data/1505611/000101376214000324/0001013762-14-000324-index.htm](https://www.sec.gov/Archives/edgar/data/1505611/000101376214000324/0001013762-14-000324-index.htm) / Accession: `0001013762-14-000324`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EX-101.INS  Inline XBRL Instance Document
EX-101.SCH  Inline XBRL Taxonomy Extension Schema
EX-101.CAL  Inline XBRL Taxonomy Extension Calculation Linkbase
EX-101.DEF  Inline XBRL Taxonomy Extension Definition Linkbase
EX-101.LAB  Inline XBRL Taxonomy Extension Label Linkbase
EX-101.PRE  Inline XBRL Taxonomy Extension Presentation Linkbase
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:EX-101\.(?:INS|SCH|CAL|DEF|LAB|PRE)|Interactive\s+Data\s+File|Inline\s+XBRL\s+Taxonomy\s+Extension) ` OR raw XML namespaces `http://www.xbrl.org/`.
  - Disambiguation Rule: Exhibits indexed with `.INS`, `.SCH`, `.CAL`, `.DEF`, `.LAB`, `.PRE` extensions or explicit references to `Interactive Data File`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:EX-101\.(?:INS|SCH|CAL|DEF|LAB|PRE)|http://www\.xbrl\.org/|xmlns:xbrli?|Taxonomy\s+Extension\s+(?:Schema|Linkbase))",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Mentions of XBRL in accounting footnotes.
  - Mitigation: Check for technical XML linkbase declarations or explicit exhibit index listings.

---

#### EX-104 — Cover Page Interactive Data File
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(104) & 17 CFR § 232.406 (Rule 406 of Regulation S-T)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Oracle Corporation` (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1341439/000119312524227971/d832518d8k.htm](https://www.sec.gov/Archives/edgar/data/1341439/000119312524227971/d832518d8k.htm) / Accession: `0001193125-24-227971`
  2. `Republic Services, Inc.` (SIC 4953 — Refuse Systems; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1060391/000106039126000273/rsg-20260806.htm](https://www.sec.gov/Archives/edgar/data/1060391/000106039126000273/rsg-20260806.htm) / Accession: `0001060391-26-000273`
  3. `Clear Channel Outdoor Holdings, Inc.` (SIC 7310 — Services-Advertising; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1334978/000119312520084396/d904800d8k.htm](https://www.sec.gov/Archives/edgar/data/1334978/000119312520084396/d904800d8k.htm) / Accession: `0001193125-20-084396`
  4. `Stratasys Ltd.` (SIC 3577 — Computer Storage Devices; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1517396/000162828025023630/0001628280-25-023630-index.htm](https://www.sec.gov/Archives/edgar/data/1517396/000162828025023630/0001628280-25-023630-index.htm) / Accession: `0001628280-25-023630`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit No.  Description
104          Cover Page Interactive Data File (the cover page XBRL tags are embedded
             within the Inline XBRL document).
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:Cover\s+Page\s+Interactive\s+Data\s+File|EX-104) `
  - Disambiguation Rule: Appears in the exhibit table referencing `Cover Page Interactive Data File` with notation `embedded within the Inline XBRL document` or `contained in Exhibit 101`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:EX-104 |Cover\s+Page\s+Interactive\s+Data\s+File)[\s\S]{0,150}?"
    r"(?:embedded\s+within\s+(?:the\s+)?Inline\s+XBRL|formatted\s+as\s+Inline\s+XBRL|contained\s+in\s+Exhibit\s+101)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Standard cover pages of periodic reports without the interactive data tag index.
  - Mitigation: Require co-occurrence of `Interactive Data File` and `Inline XBRL`.

---

## PART II: TIER 2 — MEDIUM PREVALENCE (TRANSACTION-SPECIFIC, GOVERNANCE, & COMMON EVENT-DRIVEN FILINGS)

### Tier 2 Overview Table

| Exhibit ID | Exhibit Title (Item 601) | Validated Link Count | Top Line Range | Primary Detection Prose Keywords | Secondary Disambiguation Tokens |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **EX-1** | Underwriting Agreements | 4 | Lines 1–12 | `UNDERWRITING AGREEMENT`, `PURCHASE AGREEMENT`, `UNDERWRITING AGREEMENT STANDARD PROVISIONS` | `Underwriters`, `Representative of the several Underwriters`, `Firm Shares`, `Purchase Price`, `Registration Statement` |
| **EX-2** | Plan of Acquisition, Reorganization, Arrangement, Liquidation, or Succession | 4 | Lines 1–10 | `AGREEMENT AND PLAN OF MERGER`, `PLAN OF REORGANIZATION`, `ACQUISITION AGREEMENT`, `PLAN OF LIQUIDATION` | `Merger Sub`, `Surviving Corporation`, `Effective Time`, `Section 251`, `Delaware General Corporation Law` |
| **EX-5** | Opinion re Legality | 4 | Lines 1–15 | `OPINION OF [COUNSEL]`, `VALIDITY OF THE SECURITIES`, `LEGALITY OF SHARES`, `VALIDLY ISSUED, FULLY PAID AND NON-ASSESSABLE` | `Registration Statement on Form S-3`, `binding obligations of the Company`, `consent to the filing of this opinion as an exhibit` |
| **EX-8** | Opinion re Tax Matters | 4 | Lines 1–15 | `TAX OPINION`, `OPINION RE TAX MATTERS`, `U.S. FEDERAL INCOME TAX CONSIDERATIONS`, `TAX CONSEQUENCES` | `Section 368(a)`, `reorganization within the meaning of Section 368`, `Internal Revenue Code of 1986`, `taxable REIT subsidiary` |
| **EX-14** | Code of Ethics | 4 | Lines 1–8 | `CODE OF ETHICS`, `CODE OF BUSINESS CONDUCT AND ETHICS`, `CODE OF CONDUCT` | `Item 406 of Regulation S-K`, `Senior Financial Officers`, `Chief Executive Officer and Senior Financial Officers`, `conflict of interest` |
| **EX-15** | Letter re Unaudited Interim Financial Information | 4 | Lines 1–12 | `ACCOUNTANT'S AWARENESS LETTER`, `LETTER RE UNAUDITED INTERIM FINANCIAL INFORMATION`, `LETTER IN LIEU OF CONSENT` | `Rule 436(c)`, `not considered a part of the Registration Statement prepared or certified by an accountant within the meaning of Sections 7 and 11` |
| **EX-16** | Letter re Change in Certifying Accountant | 4 | Lines 1–10 | `LETTER FROM [ACCOUNTANT]`, `ITEM 4.01 OF FORM 8-K`, `CHANGE IN CERTIFYING ACCOUNTANT` | `Securities and Exchange Commission`, `Commissioners:`, `We have read the statements made by [Company]`, `We agree with the statements` |
| **EX-17** | Correspondence on Departure of Director | 4 | Lines 1–8 | `RESIGNATION LETTER`, `RESIGNATION AS A DIRECTOR`, `TENDER MY RESIGNATION FROM THE BOARD OF DIRECTORS` | `Board of Directors`, `effective immediately`, `disagreement with the Company on any matter relating to operations, policies or practices` |
| **EX-18** | Letter re Change in Accounting Principles | 4 | Lines 1–12 | `PREFERABILITY LETTER`, `LETTER RE CHANGE IN ACCOUNTING PRINCIPLES` | `preferable`, `change in accounting principle`, `Accounting Standards Codification 250`, `Accounting Principles Board Opinion No. 20` |
| **EX-19** | Insider Trading Policies and Procedures | 4 | Lines 1–8 | `INSIDER TRADING POLICY`, `INSIDER TRADING COMPLIANCE POLICY`, `SPECIAL TRADING PROCEDURES` | `Item 408(b) of Regulation S-K`, `Material Nonpublic Information`, `Rule 10b5-1`, `Trading Windows`, `Blackout Period` |
| **EX-22** | Subsidiary Guarantors and Issuers of Guaranteed Securities | 4 | Lines 1–8 | `SUBSIDIARY GUARANTORS AND ISSUERS OF GUARANTEED SECURITIES`, `LIST OF GUARANTOR SUBSIDIARIES`, `GUARANTEED SECURITIES` | `Senior Notes`, `100% owned operating subsidiary`, `full and unconditional guarantee`, `obligors under the`, `collateralized by` |
| **EX-25** | Statement of Eligibility of Trustee (Form T-1) | 4 | Lines 1–10 | `FORM T-1`, `STATEMENT OF ELIGIBILITY UNDER THE TRUST INDENTURE ACT OF 1939`, `TRUST INDENTURE ACT` | `Trustee`, `National Association`, `Comptroller of the Currency`, `Item 1. General Information`, `Item 16. List of Exhibits` |
| **EX-97** | Clawback Policy (Recovery of Erroneously Awarded Compensation) | 4 | Lines 1–8 | `INCENTIVE COMPENSATION RECOVERY POLICY`, `CLAWBACK POLICY`, `EXECUTIVE OFFICER INCENTIVE COMPENSATION RECOVERY POLICY` | `Rule 10D-1`, `Accounting Restatement`, `Erroneously Awarded Compensation`, `Financial Reporting Measure`, `Big R restatement` |
| **EX-99** | Additional Exhibits / Earnings Releases | 4 | Lines 1–8 | `FOR IMMEDIATE RELEASE`, `NEWS RELEASE`, `PRESS RELEASE`, `INVESTOR PRESENTATION` | `Exhibit 99.1`, `Item 2.02`, `Financial Results`, `Non-GAAP Financial Measures`, `Forward-Looking Statements` |
| **EX-107** | Filing Fee Table | 4 | Lines 1–8 | `CALCULATION OF FILING FEE TABLES`, `FILING FEE TABLE`, `EX-FILING FEES`, `EXHIBIT 107` | `Rule 457`, `Fee Calculation Table`, `Proposed Maximum Offering Price Per Share`, `Amount of Registration Fee` |

---

### Tier 2 Deep-Dive Profiles

#### EX-1 — Underwriting Agreements
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(1)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Spruce Biosciences, Inc.` (SIC 2834 — Pharmaceutical Preparations; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1683553/000119312526167332/sprb-ex1_1.htm](https://www.sec.gov/Archives/edgar/data/1683553/000119312526167332/sprb-ex1_1.htm) / Accession: `0001193125-26-167332`
  2. `Tencent Music Entertainment Group` (SIC 7370 — Computer Services; Foreign Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1744676/000119312518340313/d624633dex11.htm](https://www.sec.gov/Archives/edgar/data/1744676/000119312518340313/d624633dex11.htm) / Accession: `0001193125-18-340313`
  3. `Exxon Mobil Corporation` (SIC 2911 — Petroleum Refining; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/2115436/000119312526402986/d15072dex11.htm](https://www.sec.gov/Archives/edgar/data/2115436/000119312526402986/d15072dex11.htm) / Accession: `0001193125-26-402986`
  4. `Rivian Automotive, Inc.` (SIC 3711 — Motor Vehicles & Car Bodies; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1874178/000110465926081988/tm2617163d3_ex1-1.htm](https://www.sec.gov/Archives/edgar/data/1874178/000110465926081988/tm2617163d3_ex1-1.htm) / Accession: `0001104659-26-081988`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 1.1
75,000,000 Shares
Rivian Automotive, Inc.
Class A Common Stock, Par Value $0.001 Per Share
UNDERWRITING AGREEMENT
July 7, 2026
Goldman Sachs & Co. LLC
As representative of the several Underwriters named in Schedule I hereto
Ladies and Gentlemen:
Rivian Automotive, Inc., a Delaware corporation (the “Company”), proposes to issue and sell to the several Underwriters...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:UNDERWRITING\s+AGREEMENT|PURCHASE\s+AGREEMENT\s+\(UNDERWRITING\)) `
  - Disambiguation Rule: Identifies syndicate intermediaries: `Underwriters`, `Representative of the several Underwriters`, `Purchase Price`, and `Firm Shares` or `Option Shares`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+1(?:\.1)?\s+)?[\s\S]{0,250}? UNDERWRITING\s+AGREEMENT [\s\S]{1,400}?"
    r"(?:several\s+Underwriters|as\s+Representative|Firm\s+Shares)",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Debt purchase agreements or credit agreements (EX-10).
  - Mitigation: Enforce presence of `Underwriters` / `Representative` and exclude `Administrative Agent` or `Borrower`.

---

#### EX-2 — Plan of Acquisition, Reorganization, Arrangement, Liquidation, or Succession
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(2)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Twenty-First Century Fox, Inc. / The Walt Disney Company` (SIC 4833 — Television Broadcasting; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1308161/000119312517370718/d489755dex21.htm](https://www.sec.gov/Archives/edgar/data/1308161/000119312517370718/d489755dex21.htm) / Accession: `0001193125-17-370718`
  2. `Discovery Communications, Inc. / Scripps Networks` (SIC 4841 — Cable Television; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1437107/000119312517241440/d433093dex21.htm](https://www.sec.gov/Archives/edgar/data/1437107/000119312517241440/d433093dex21.htm) / Accession: `0001193125-17-241440`
  3. `Amazon.com, Inc. / Whole Foods Market, Inc.` (SIC 5961 — Retail; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1018724/000119312517205287/d352949dex21.htm](https://www.sec.gov/Archives/edgar/data/1018724/000119312517205287/d352949dex21.htm) / Accession: `0001193125-17-205287`
  4. `Alphabet Inc.` (SIC 7370 — Computer Programming, Data Processing; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1652044/000119312515336577/d82837dex21.htm](https://www.sec.gov/Archives/edgar/data/1652044/000119312515336577/d82837dex21.htm) / Accession: `0001193125-15-336577`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 2.1
AGREEMENT AND PLAN OF MERGER
among
TWENTY-FIRST CENTURY FOX, INC.,
THE WALT DISNEY COMPANY,
TWC MERGER SUB, INC.
and
WTW MERGER SUB, LLC
Dated as of December 13, 2017
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:AGREEMENT\s+AND\s+PLAN\s+OF\s+MERGER|PLAN\s+OF\s+(?:REORGANIZATION|LIQUIDATION|ARRANGEMENT)|ASSET\s+PURCHASE\s+AGREEMENT\s+AND\s+PLAN\s+OF\s+REORGANIZATION) `
  - Disambiguation Rule: Invariant transactional structure: contains `Merger Sub`, `Surviving Corporation`, `Effective Time`, and statutory merger authority (`DGCL Section 251`).
  - Suggested Regex / Logic:
```python
re.compile(
    r" (?:AGREEMENT\s+AND\s+PLAN\s+OF\s+MERGER|PLAN\s+OF\s+(?:REORGANIZATION|LIQUIDATION|ARRANGEMENT)) [\s\S]{1,500}?"
    r"(?:Merger\s+Sub|Surviving\s+Corporation|Effective\s+Time)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Commercial joint ventures filed under EX-10 mentioning mergers.
  - Mitigation: The title line in lines 1–6 must be the standalone agreement title, followed by `among` / `by and between` naming `Parent`, `Merger Sub`, and `Company`.

---

#### EX-5 — Opinion re Legality
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(5)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Petrobras / Petroleo Brasileiro S.A.` (Latham & Watkins LLP) (SIC 1311; Foreign Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1375877/000114554908001294/h02300exv5w1.htm](https://www.sec.gov/Archives/edgar/data/1375877/000114554908001294/h02300exv5w1.htm) / Accession: `0001145549-08-001294`
  2. `Barclays PLC` (Cleary Gottlieb Steen & Hamilton LLP) (SIC 6029; Foreign Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/312069/000119312526284760/d121908dex51.htm](https://www.sec.gov/Archives/edgar/data/312069/000119312526284760/d121908dex51.htm) / Accession: `0001193125-26-284760`
  3. `Flextronics International Ltd.` (Allen & Gledhill LLP) (SIC 3672; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1105101/000114554908000057/h01807exv5w1.htm](https://www.sec.gov/Archives/edgar/data/1105101/000114554908000057/h01807exv5w1.htm) / Accession: `0001145549-08-000057`
  4. `Oracle Corporation` (Freshfields Bruckhaus Deringer US LLP) (SIC 7372; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1341439/000119312524227971/d832518d8k.htm](https://www.sec.gov/Archives/edgar/data/1341439/000119312524227971/d832518d8k.htm) / Accession: `0001193125-24-227971`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 5.1
CLEARY GOTTLIEB STEEN & HAMILTON LLP
One Liberty Plaza
New York, NY 10006
June 26, 2026
Barclays PLC
1 Churchill Place
London E14 5HP
Ladies and Gentlemen:
We have acted as special United States counsel to Barclays PLC... in connection with the Registration Statement...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:validly\s+issued,\s+fully\s+paid\s+and\s+non[- ]assessable|binding\s+obligations\s+of\s+the\s+Company|Validity\s+of\s+the\s+Securities|Legality\s+of\s+(?:the\s+)?Shares) `
  - Disambiguation Rule: Core legal conclusion: equity will be `validly issued, fully paid and non-assessable`, or debt will constitute `valid and binding obligations`, coupled with consent to file under Item 601(b)(5).
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Registration\s+Statement\s+on\s+Form\s+S-[\d]|Validity\s+of\s+(?:the\s+)?(?:Securities|Notes|Shares))[\s\S]{1,600}?"
    r"(?:validly\s+issued,\s*fully\s+paid\s+and\s+non[- ]assessable|legally\s+valid\s+and\s+binding\s+obligations)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: EX-8 Tax Opinions issued by the same law firm.
  - Mitigation: EX-5 focuses strictly on corporate authorization and validity of issuance (`validly issued, fully paid and non-assessable`). EX-8 focuses on tax classification.

---

#### EX-8 — Opinion re Tax Matters
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(8)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Tenaris S.A.` (Sullivan & Cromwell LLP) (SIC 3312; Foreign Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1142206/000114554907002263/k01469exv8w1.htm](https://www.sec.gov/Archives/edgar/data/1142206/000114554907002263/k01469exv8w1.htm) / Accession: `0001145549-07-002263`
  2. `Bioverativ Inc.` (Paul, Weiss, Rifkind, Wharton & Garrison LLP) (SIC 2836; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1709164/000119312517262713/d374435dex81.htm](https://www.sec.gov/Archives/edgar/data/1709164/000119312517262713/d374435dex81.htm) / Accession: `0001193125-17-262713`
  3. `Alexandria Real Estate Equities, Inc.` (Morrison & Foerster LLP) (SIC 6798; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/826675/000082667526000085/exhibit81taxopinionamendme.htm](https://www.sec.gov/Archives/edgar/data/826675/000082667526000085/exhibit81taxopinionamendme.htm) / Accession: `0000826675-26-000085`
  4. `Alpine Income Property Trust, Inc.` (Vinson & Elkins L.L.P.) (SIC 6798; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1786117/000110465926110426/tm2626043d1_ex8-1.htm](https://www.sec.gov/Archives/edgar/data/1786117/000110465926110426/tm2626043d1_ex8-1.htm) / Accession: `0001104659-26-110426`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 8.1
Alpine Income Property Trust, Inc.
Ladies and Gentlemen:
We have acted as counsel to Alpine Income Property Trust, Inc., a Maryland corporation (the “Company”),
in connection with the preparation of a Registration Statement on Form S-3...
You have requested our opinion regarding certain U.S. federal income tax matters.
In connection with the opinions rendered in (a) and (b) below (together, the “Tax Opinion”)...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:TAX\s+OPINION|OPINION\s+REGARDING\s+TAX\s+MATTERS|U\.?S\.?\s+FEDERAL\s+INCOME\s+TAX\s+(?:MATTERS|CONSEQUENCES|CONSIDERATIONS)) `
  - Disambiguation Rule: References `Internal Revenue Code of 1986`, `tax consequences of the transaction`, `reorganization within the meaning of Section 368`, or qualification as a `real estate investment trust (REIT) under Section 856`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:TAX\s+OPINION|opinion\s+(?:with\s+respect\s+to|regarding)\s+certain\s+(?:U\.?S\.?\s+federal\s+income\s+)?tax\s+matters)"
    r"[\s\S]{1,600}?(?:Internal\s+Revenue\s+Code|Section\s+368|tax\s+treatment\s+of\s+the\s+merger|qualif(?:y|ication)\s+as\s+a\s+REIT)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Legal opinions under EX-5 with brief tax summaries.
  - Mitigation: EX-8 focuses substantively on the Internal Revenue Code, whereas EX-5 limits its core holding to `validly issued, fully paid and non-assessable`.

---

#### EX-14 — Code of Ethics
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(14) & 17 CFR § 229.406 (Item 406 of Regulation S-K)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `ESPRE Solutions, Inc.` (SIC 7372 — Prepackaged Software; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1304588/000095014407010099/g10193exv14w1.htm](https://www.sec.gov/Archives/edgar/data/1304588/000095014407010099/g10193exv14w1.htm) / Accession: `0000950144-07-010099`
  2. `Integrated Rail and Resources Acquisition Corp.` (SIC 6770 — Blank Checks; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1854795/000119312521169327/d91862dex141.htm](https://www.sec.gov/Archives/edgar/data/1854795/000119312521169327/d91862dex141.htm) / Accession: `0001193125-21-169327`
  3. `The Hartford Financial Services Group, Inc.` (SIC 6331 — Insurance; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/874766/000095012305008662/y10841exv14w1.htm](https://www.sec.gov/Archives/edgar/data/874766/000095012305008662/y10841exv14w1.htm) / Accession: `0000950123-05-008662`
  4. `Super League Enterprise, Inc.` (SIC 7370 — Computer Programming, Data Processing; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/1816937/000149315224012367/ex14-1.htm](https://www.sec.gov/Archives/edgar/data/1816937/000149315224012367/ex14-1.htm) / Accession: `0001493152-24-012367`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EX-14.1
Exhibit 14.1
THE HARTFORD FINANCIAL SERVICES GROUP, INC.
CODE OF ETHICS AND BUSINESS CONDUCT
FOR SENIOR FINANCIAL OFFICERS
Introduction
This Code of Ethics and Business Conduct applies to the Chief Executive Officer,
Chief Financial Officer, Controller, and persons performing similar functions...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:CODE\s+OF\s+ETHICS(?:\s+AND\s+BUSINESS\s+CONDUCT)?|CODE\s+OF\s+BUSINESS\s+CONDUCT(?:\s+AND\s+ETHICS)?) `
  - Disambiguation Rule: Invariant coverage mandated by Item 406: applies to `Chief Executive Officer, Chief Financial Officer, Controller or Principal Accounting Officer`, focusing on `honest and ethical conduct`, `conflicts of interest`, and `full, fair, accurate, timely disclosure`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+14(?:\.1)?\s+)?[\w\s.,–—-]+? CODE\s+OF\s+(?:ETHICS|BUSINESS\s+CONDUCT) [\s\S]{1,400}?"
    r"(?:Senior\s+Financial\s+Officers|Principal\s+Executive\s+Officer|honest\s+and\s+ethical\s+conduct|Item\s+406)",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Employee compliance guides filed under EX-99.
  - Mitigation: Require the explicit title `CODE OF ETHICS` or `CODE OF BUSINESS CONDUCT` and the specific reference to principal executive/financial officers.

---

#### EX-15 — Letter re Unaudited Interim Financial Information
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(15) & 17 CFR § 230.436(c) (Rule 436(c) of Securities Act)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `UnitedHealth Group Incorporated` (Deloitte & Touche LLP) (SIC 6324 — Medical Plans; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/731766/000119312505165298/dex151.htm](https://www.sec.gov/Archives/edgar/data/731766/000119312505165298/dex151.htm) / Accession: `0001193125-05-165298`
  2. `MidAmerican Energy Company` (Deloitte & Touche LLP) (SIC 4924 — Natural Gas; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/928576/000092857615000009/mec33115ex151.htm](https://www.sec.gov/Archives/edgar/data/928576/000092857615000009/mec33115ex151.htm) / Accession: `0000928576-15-000009`
  3. `BreitBurn Energy Partners L.P.` (PwC LLP) (SIC 1311 — Oil & Gas; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1357371/000119312513382452/d602407dex151.htm](https://www.sec.gov/Archives/edgar/data/1357371/000119312513382452/d602407dex151.htm) / Accession: `0001193125-13-382452`
  4. `Dynacq Healthcare, Inc.` (KWCO, P.C.) (SIC 8062 — Hospitals; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/890908/000119312512302072/d372122dex151.htm](https://www.sec.gov/Archives/edgar/data/890908/000119312512302072/d372122dex151.htm) / Accession: `0001193125-12-302072`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 15.1
Awareness Letter of Independent Accountants
To the Board of Directors of MidAmerican Energy Company:
We have reviewed, in accordance with the standards of the Public Company Accounting Oversight Board (United States),
the unaudited interim financial information of MidAmerican Energy Company for the periods ended March 31, 2015...
because we did not perform an audit, we expressed no opinion on that information.
We also are aware that the aforementioned report, pursuant to Rule 436(c) under the Securities Act of 1933,
is not considered a part of the Registration Statement...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:Rule\s+436\(c\)|Awareness\s+Letter|Letter\s+re\s+unaudited\s+interim\s+financial\s+information|Letter\s+in\s+lieu\s+of\s+consent) `
  - Disambiguation Rule: Mentions `Rule 436(c) under the Securities Act of 1933` and affirms that the unaudited review report `is not considered a part of the Registration Statement prepared or certified by an accountant within the meaning of Sections 7 and 11 of that Act`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Rule\s+436\(c\)|unaudited\s+interim\s+financial\s+information)[\s\S]{1,400}?"
    r"(?:not\s+considered\s+a\s+part\s+of\s+the\s+Registration\s+Statement|within\s+the\s+meaning\s+of\s+Sections?\s+7\s+and\s+11)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Auditor consents under EX-23.
  - Mitigation: EX-23 provides an affirmative consent ("We consent to the incorporation by reference"). EX-15 is an awareness letter specifically disclaiming Section 7/11 liability under Rule 436(c).

---

#### EX-16 — Letter re Change in Certifying Accountant
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(16) & 17 CFR § 229.304 (Item 304 of Regulation S-K)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Alteryx, Inc.` (PricewaterhouseCoopers LLP) (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1689923/000119312519016035/d669577dex161.htm](https://www.sec.gov/Archives/edgar/data/1689923/000119312519016035/d669577dex161.htm) / Accession: `0001193125-19-016035`
  2. `Allied Energy, Inc.` (Victor Mokuolu, CPA PLLC) (SIC 1311 — Crude Petroleum; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/1109262/000168316826001486/aggi_ex1601.htm](https://www.sec.gov/Archives/edgar/data/1109262/000168316826001486/aggi_ex1601.htm) / Accession: `0001683168-26-001486`
  3. `ATI Physical Therapy, Inc.` (PricewaterhouseCoopers LLP) (SIC 8049 — Health Practitioners; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1815849/000114036123017517/brhc10051214_ex16-1.htm](https://www.sec.gov/Archives/edgar/data/1815849/000114036123017517/brhc10051214_ex16-1.htm) / Accession: `0001140361-23-017517`
  4. `Bankwell Financial Group, Inc.` (Whittlesey & Hadley, P.C.) (SIC 6022 — Commercial Banks; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1505732/000091426017000023/bwfg8k-4717.htm](https://www.sec.gov/Archives/edgar/data/1505732/000091426017000023/bwfg8k-4717.htm) / Accession: `0000914260-17-000023`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 16.1
PricewaterhouseCoopers LLP
488 Almaden Boulevard
San Jose, CA 95110
January 24, 2019
Securities and Exchange Commission
100 F Street, N.E.
Washington, D.C. 20549
Commissioners:
We have read the statements made by Alteryx, Inc. (copy attached), which we understand will be filed
with the Securities and Exchange Commission, pursuant to Item 4.01 of Form 8-K of Alteryx, Inc.
We agree with the statements concerning our Firm contained therein.
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:Item\s+4\.01\s+of\s+Form\s+8-K|change\s+in\s+(?:registrant['’]?s\s+)?certifying\s+accountant|Item\s+304\s+of\s+Regulation\s+S-K) `
  - Disambiguation Rule: Addressed directly to the `Securities and Exchange Commission` / `Commissioners:`; stated by the former independent accounting firm confirming whether it `agrees` or `does not agree` with the disclosures under Item 4.01 of Form 8-K.
  - Suggested Regex / Logic:
```python
re.compile(
    r"Securities\s+and\s+Exchange\s+Commission[\s\S]{1,400}?"
    r"(?:Item\s+4\.01\s+of\s+Form\s+8-K|Item\s+304(?:\(a\))?\s+of\s+Regulation\s+S-K)[\s\S]{1,250}?"
    r"(?:agree\s+with\s+the\s+statements|stating\s+the\s+respects\s+in\s+which\s+it\s+does\s+not\s+agree)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Current Report Form 8-K Item 4.01 body text.
  - Mitigation: EX-16 is a standalone letter on accounting firm letterhead addressed to `Securities and Exchange Commission` signed by the CPA firm.

---

#### EX-17 — Correspondence on Departure of Director
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(17)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Duos Technologies Group, Inc.` (SIC 7372 — Prepackaged Software; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1396536/000155335017001423/duot_ex17z1.htm](https://www.sec.gov/Archives/edgar/data/1396536/000155335017001423/duot_ex17z1.htm) / Accession: `0001553350-17-001423`
  2. `Power Solutions International, Inc.` (SIC 3510 — Engines & Turbines; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1137091/000119312525168135/d830335dex171.htm](https://www.sec.gov/Archives/edgar/data/1137091/000119312525168135/d830335dex171.htm) / Accession: `0001193125-25-168135`
  3. `Digital Realty Trust, Inc.` (SIC 6798 — Real Estate Investment Trusts; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1297996/000119312523161886/d434156dex171.htm](https://www.sec.gov/Archives/edgar/data/1297996/000119312523161886/d434156dex171.htm) / Accession: `0001193125-23-161886`
  4. `BioDelivery Sciences International, Inc.` (SIC 2834 — Pharmaceutical Preparations; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1103021/000119312504157011/dex171.htm](https://www.sec.gov/Archives/edgar/data/1103021/000119312504157011/dex171.htm) / Accession: `0001193125-04-157011`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EXHIBIT 17.1
November 28, 2017
To the Members of the Board of Directors of Duos Technologies Group, Inc.
This letter shall serve as formal notice of my resignation, effective immediately,
from my positions as Chairman of the Compensation Committee, Chairman of the Corporate Governance
and Nominating Committee, member of the Audit Committee and member of the board of directors...
The resignation is not the result of any disagreement with the Company on any matter relating
to the Company's operations, policies or practices.
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:RESIGNATION\s+(?:AS\s+A\s+DIRECTOR|LETTER)|tender\s+my\s+resignation\s+as\s+a\s+member\s+of\s+the\s+Board\s+of\s+Directors|resign\s+from\s+the\s+Board\s+of\s+Directors) `
  - Disambiguation Rule: Personal letter addressed to the `Board of Directors` or `Chairman of the Board`; states `hereby resign` / `tender my resignation` from the Board, and typically affirms whether the departure involves a disagreement on `operations, policies or practices`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Board\s+of\s+Directors|Chairman\s+of\s+the\s+Board)[\s\S]{1,350}?"
    r"(?:(?:hereby\s+)?(?:submit|tender)\s+my\s+resignation|resign\s+(?:from\s+my\s+position\s+)?as\s+(?:a\s+)?(?:member\s+of\s+the\s+Board|Director))",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Form 8-K Item 5.02 narrative summarizing the departure.
  - Mitigation: EX-17 is written in the first person (`I hereby resign`, `my decision to resign`) and formatted as correspondence from the individual director.

---

#### EX-18 — Letter re Change in Accounting Principles
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(18)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Plains All American Pipeline, L.P.` (PwC LLP) (SIC 4610 — Pipelines; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1070423/000104746904025696/a2141170zex-18_1.htm](https://www.sec.gov/Archives/edgar/data/1070423/000104746904025696/a2141170zex-18_1.htm) / Accession: `0001047469-04-025696`
  2. `OraSure Technologies, Inc.` (KPMG LLP) (SIC 2835 — Diagnostics; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1116463/000111646325000038/preferabilityletter.htm](https://www.sec.gov/Archives/edgar/data/1116463/000111646325000038/preferabilityletter.htm) / Accession: `0001116463-25-000038`
  3. `CSW Industrials, Inc.` (Grant Thornton LLP) (SIC 2890 — Chemical Products; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1624794/000162479422000040/csw-preferabilityletterfor.htm](https://www.sec.gov/Archives/edgar/data/1624794/000162479422000040/csw-preferabilityletterfor.htm) / Accession: `0001624794-22-000040`
  4. `Clean Harbors, Inc.` (Deloitte & Touche LLP) (SIC 4955 — Hazardous Waste; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/858877/000119312505231378/dex181.htm](https://www.sec.gov/Archives/edgar/data/858877/000119312505231378/dex181.htm) / Accession: `0001193125-05-231378`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 18.1
Board of Directors
OraSure Technologies, Inc.
Dear Directors:
We are providing this letter solely for inclusion as an exhibit to OraSure Technologies Inc.'s
Quarterly Report on Form 10-Q for the quarterly period ended March 31, 2025...
the Company changed its accounting for inventory costing from the first-in, first-out (“FIFO”) method
to average cost... we concur with management that the newly adopted method of accounting is preferable...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:PREFERABILITY\s+LETTER|change\s+in\s+accounting\s+principle\s+is\s+preferable|newly\s+adopted\s+method\s+of\s+accounting\s+is\s+preferable) `
  - Disambiguation Rule: Invariant accounting preferability phrase: `concur with management that [such change / the newly adopted method] is preferable in the [Company's] circumstances` under `ASC 250` or `APB Opinion No. 20`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:change\s+in\s+accounting\s+principle|accounting\s+change)[\s\S]{1,400}?"
    r"(?:concur\s+with\s+management\s+that[\s\S]{1,100}?is\s+preferable|preferability\s+of\s+one\s+acceptable\s+method)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Note 1 of Form 10-Q explaining the accounting change.
  - Mitigation: EX-18 is signed and delivered by the independent CPA firm (`Very truly yours, /s/ KPMG LLP`), addressed to the Board of Directors, and contains auditor concurrence on preferability.

---

#### EX-19 — Insider Trading Policies and Procedures
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(19) & 17 CFR § 229.408(b) (Item 408(b) of Regulation S-K)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Microsoft Corporation` (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-ex19_1.htm](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-ex19_1.htm) / Accession: `0001193125-26-323660`
  2. `Apple Inc.` (SIC 3571 — Electronic Computers; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/a10-kexhibit1919282024.htm](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/a10-kexhibit1919282024.htm) / Accession: `0000320193-24-000123`
  3. `enGene Holdings Inc.` (SIC 2836 — Biological Products; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1980845/000095017024138472/engn-ex19_1.htm](https://www.sec.gov/Archives/edgar/data/1980845/000095017024138472/engn-ex19_1.htm) / Accession: `0000950170-24-138472`
  4. `Zeta Global Holdings Corp.` (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1851003/000095017025027338/zeta-ex19_1.htm](https://www.sec.gov/Archives/edgar/data/1851003/000095017025027338/zeta-ex19_1.htm) / Accession: `0000950170-25-027338`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 19.1
General Insider Trading Policy
1. PURPOSE
To prevent the misuse of material, nonpublic information about Microsoft or other companies,
and to avoid even the appearance of impropriety.
2. SCOPE
This policy applies to all employees, directors, and officers of Microsoft Corporation and its subsidiaries...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:INSIDER\s+TRADING\s+(?:COMPLIANCE\s+)?POLICY|POLICY\s+ON\s+INSIDER\s+TRADING\s+AND\s+TIPPING) `
  - Disambiguation Rule: Specifies trading prohibitions based on `material, nonpublic information`, establishes `Trading Windows`, `Blackout Periods`, and `Rule 10b5-1 Trading Plans`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+19(?:\.1)?\s+)?[\w\s.,–—-]+? INSIDER\s+TRADING\s+(?:COMPLIANCE\s+)?POLICY [\s\S]{1,400}?"
    r"(?:material,\s*nonpublic\s+information|Rule\s+10b5-1|blackout\s+period)",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Code of Ethics (EX-14) containing an insider trading clause.
  - Mitigation: EX-19 is dedicated exclusively to trading policies under Item 408(b); verify the document header is titled `INSIDER TRADING POLICY` and not `CODE OF ETHICS`.

---

#### EX-22 — Subsidiary Guarantors and Issuers of Guaranteed Securities
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(22) & 17 CFR § 210.13-01 / 13-02
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Dell Technologies Inc.` (SIC 3571 — Electronic Computers; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1571996/000157199626000046/exhibit221-fy27q2.htm](https://www.sec.gov/Archives/edgar/data/1571996/000157199626000046/exhibit221-fy27q2.htm) / Accession: `0001571996-26-000046`
  2. `Waters Corporation` (SIC 3826 — Laboratory Analytical Instruments; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1000697/000119312526107398/d122041dex221.htm](https://www.sec.gov/Archives/edgar/data/1000697/000119312526107398/d122041dex221.htm) / Accession: `0001193125-26-107398`
  3. `T-Mobile US, Inc.` (SIC 4812 — Radiotelephone Communications; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1283699/000128369926000101/tmus06302026ex221.htm](https://www.sec.gov/Archives/edgar/data/1283699/000128369926000101/tmus06302026ex221.htm) / Accession: `0001283699-26-000101`
  4. `The Kraft Heinz Company` (SIC 2030 — Canned & Preserved Food; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1637459/000163745926000022/exhibit221q12026.htm](https://www.sec.gov/Archives/edgar/data/1637459/000163745926000022/exhibit221q12026.htm) / Accession: `0001637459-26-000022`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 22.1
Subsidiary Guarantors and Issuers of Guaranteed Securities
Guaranteed Securities
The following securities (collectively referred to in this exhibit as the “Senior Notes”)
issued by Dell International L.L.C., a Delaware limited liability company and wholly-owned subsidiary
of Dell Technologies Inc. (“Dell Technologies”), and EMC Corporation... were outstanding as of July 31, 2026.
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:Subsidiary\s+Guarantors\s+and\s+Issuers\s+of\s+Guaranteed\s+Securities|Guarantor\s+Subsidiaries|Subsidiary\s+Issuer\s+of\s+Guaranteed\s+Securities) `
  - Disambiguation Rule: Explicitly links guaranteed debt securities to entities: references `obligors`, `guarantors of registered debt securities`, or `unconditionally guaranteed by`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Subsidiary\s+Guarantors\s+and\s+Issuers\s+of\s+Guaranteed\s+Securities|List\s+of\s+Guarantor\s+Subsidiaries)"
    r"[\s\S]{1,400}?(?:guaranteed\s+securities|Senior\s+Notes|obligors\s+under|guarantee\s+registered\s+debt)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: EX-21 List of Subsidiaries.
  - Mitigation: EX-21 lists entities without debt guarantee references; EX-22 specifically references registered debt classes and guarantor/co-issuer roles.

---

#### EX-25 — Statement of Eligibility of Trustee (Form T-1)
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(25) & Trust Indenture Act Section 305(b)(2)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Citigroup Inc.` (SIC 6021 — National Commercial Banks; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/15615/000119312510268831/dex251.htm](https://www.sec.gov/Archives/edgar/data/15615/000119312510268831/dex251.htm) / Accession: `0001193125-10-268831`
  2. `The Hershey Company` (SIC 2060 — Sugar & Confectionery; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/47111/000004711121000039/exhibit251-formtx1statement.htm](https://www.sec.gov/Archives/edgar/data/47111/000004711121000039/exhibit251-formtx1statement.htm) / Accession: `0000047111-21-000039`
  3. `Tyson Foods, Inc.` (SIC 2011 — Meat Packing Plants; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/100493/000119312512261061/d361561dex251.htm](https://www.sec.gov/Archives/edgar/data/100493/000119312512261061/d361561dex251.htm) / Accession: `0001193125-12-261061`
  4. `Chesapeake Energy Corporation` (SIC 1311 — Crude Petroleum; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/895126/000119312506136812/dex251.htm](https://www.sec.gov/Archives/edgar/data/895126/000119312506136812/dex251.htm) / Accession: `0001193125-06-136812`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 25.1
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM T-1
STATEMENT OF ELIGIBILITY UNDER THE TRUST INDENTURE ACT OF 1939
OF A CORPORATION DESIGNATED TO ACT AS TRUSTEE
CHECK IF AN APPLICATION TO DETERMINE ELIGIBILITY OF A TRUSTEE PURSUANT TO SECTION 305(b)(2)
THE BANK OF NEW YORK MELLON TRUST COMPANY, N.A.
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:FORM\s+T-1|STATEMENT\s+OF\s+ELIGIBILITY\s+UNDER\s+THE\s+TRUST\s+INDENTURE\s+ACT\s+OF\s+1939) `
  - Disambiguation Rule: Form header: `FORM T-1` and `STATEMENT OF ELIGIBILITY UNDER THE TRUST INDENTURE ACT OF 1939 OF A CORPORATION DESIGNATED TO ACT AS TRUSTEE`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"FORM\s+T-1[\s\S]{1,250}?STATEMENT\s+OF\s+ELIGIBILITY\s+UNDER\s+THE\s+TRUST\s+INDENTURE\s+ACT\s+OF\s+1939",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Indentures under EX-4 mentioning Trust Indenture Act trustee eligibility.
  - Mitigation: FORM T-1 is filed on official SEC statutory form headings with banking trustee disclosures.

---

#### EX-97 — Policy Relating to Recovery of Erroneously Awarded Compensation (Clawback Policy)
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(97) & 17 CFR § 240.10D-1 (Exchange Act Rule 10D-1)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Atossa Therapeutics, Inc.` (SIC 2834 — Pharmaceutical Preparations; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1488039/000095017024039306/atos-ex97_1.htm](https://www.sec.gov/Archives/edgar/data/1488039/000095017024039306/atos-ex97_1.htm) / Accession: `0000950170-24-039306`
  2. `Sixth Street Specialty Lending, Inc.` (SIC 6221 — Commodity Contracts & Funds; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1508655/000095017024015845/tslx-ex97_1.htm](https://www.sec.gov/Archives/edgar/data/1508655/000095017024015845/tslx-ex97_1.htm) / Accession: `0000950170-24-015845`
  3. `SmartRent, Inc.` (SIC 7372 — Prepackaged Software; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1837014/000095017024025423/smrt-ex97_1.htm](https://www.sec.gov/Archives/edgar/data/1837014/000095017024025423/smrt-ex97_1.htm) / Accession: `0000950170-24-025423`
  4. `Primerica, Inc.` (SIC 6311 — Life Insurance; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1475922/000095017024022262/pri-ex97_1.htm](https://www.sec.gov/Archives/edgar/data/1475922/000095017024022262/pri-ex97_1.htm) / Accession: `0000950170-24-022262`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 97.1
Sixth Street Specialty Lending, Inc.
Incentive Compensation Clawback Policy
(As Adopted November 2023 Pursuant to NYSE Rule 303A.14)
1. Introduction
The Board of Directors (the “Board”) of Sixth Street Specialty Lending, Inc. has adopted
this policy for the recovery of erroneously awarded incentive-based compensation...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:INCENTIVE\s+COMPENSATION\s+(?:CLAWBACK|RECOVERY)\s+POLICY|CLAWBACK\s+POLICY|RECOVERY\s+OF\s+ERRONEOUSLY\s+AWARDED\s+COMPENSATION) `
  - Disambiguation Rule: Dodd-Frank Section 954 / Rule 10D-1 terminology: mandates recovery of `Erroneously Awarded Compensation` following an `Accounting Restatement` (`Big R` and `little r`) for `Covered Executives` based on `Financial Reporting Measures`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:INCENTIVE\s+COMPENSATION\s+(?:CLAWBACK|RECOVERY)\s+POLICY|COMPENSATION\s+RECOVERY\s+POLICY)"
    r"[\s\S]{1,500}?(?:Erroneously\s+Awarded\s+Compensation|Accounting\s+Restatement|Rule\s+10D-1)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Employment agreements (EX-10) containing individual clawback provisions.
  - Mitigation: EX-97 is a comprehensive policy document adopted under NYSE/Nasdaq listing standards citing Rule 10D-1.

---

#### EX-99 — Additional Exhibits / Earnings Releases
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(99)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Micron Technology, Inc.` (SIC 3674 — Semiconductors; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/723125/000072312526000018/a2026q4ex991-pressrelease.htm](https://www.sec.gov/Archives/edgar/data/723125/000072312526000018/a2026q4ex991-pressrelease.htm) / Accession: `0000723125-26-000018`
  2. `Microsoft Corporation` (SIC 7372 — Prepackaged Software; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/789019/000119312515247530/d54167dex991.htm](https://www.sec.gov/Archives/edgar/data/789019/000119312515247530/d54167dex991.htm) / Accession: `0001193125-15-247530`
  3. `Aspire Biopharma Inc.` (SIC 2834 — Pharmaceutical Preparations; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1921865/000119312526384527/aspi-ex99_1.htm](https://www.sec.gov/Archives/edgar/data/1921865/000119312526384527/aspi-ex99_1.htm) / Accession: `0001193125-26-384527`
  4. `Clear Channel Outdoor Holdings, Inc.` (SIC 7310 — Services-Advertising; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1334978/000119312520084396/d904800d8k.htm](https://www.sec.gov/Archives/edgar/data/1334978/000119312520084396/d904800d8k.htm) / Accession: `0001193125-20-084396`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 99.1
For Immediate Release
Microsoft Announces Restructuring of Phone Hardware Business
Commits to streamlining phone business near-term and reinventing mobility long-term.
REDMOND, Wash. — July 8, 2015 — Microsoft Corp. today announced plans to restructure...
For more information, press only:
Rapid Response Team, Waggener Edstrom Communications...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:FOR\s+IMMEDIATE\s+RELEASE|NEWS\s+RELEASE|PRESS\s+RELEASE|INVESTOR\s+PRESENTATION) `
  - Disambiguation Rule: Header contains `FOR IMMEDIATE RELEASE` followed by dateline: `[CITY], [STATE] — [DATE] — [Company] today announced` and contact details (`Media Relations`, `Investor Relations`).
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:FOR\s+IMMEDIATE\s+RELEASE|NEWS\s+RELEASE|PRESS\s+RELEASE)[\s\S]{1,400}?"
    r"(?:—\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{4}\s*—|Media\s+Contact|Investor\s+Relations)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Form 8-K Item 2.02 or 7.01 body text summarizing earnings releases.
  - Mitigation: The 8-K body introduces the exhibit; EX-99.1 is the verbatim press release itself.

---

#### EX-107 — Filing Fee Table
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(107) & 17 CFR § 232.408 (Rule 408 of Regulation S-T)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Silk Road Medical, Inc.` (SIC 3841 — Surgical Instruments; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1397702/000139770223000037/silk-20230509xex10_7.htm](https://www.sec.gov/Archives/edgar/data/1397702/000139770223000037/silk-20230509xex10_7.htm) / Accession: `0001397702-23-000037`
  2. `Root, Inc.` (SIC 6331 — Insurance; Smaller Reporting) — [https://www.sec.gov/Archives/edgar/data/1788882/000178888222000014/calculationoffilingfeetable.htm](https://www.sec.gov/Archives/edgar/data/1788882/000178888222000014/calculationoffilingfeetable.htm) / Accession: `0001788882-22-000014`
  3. `Bumble Inc.` (SIC 7370 — Computer Services; Large Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1830043/000119312526111127/d917042dexfilingfees.htm](https://www.sec.gov/Archives/edgar/data/1830043/000119312526111127/d917042dexfilingfees.htm) / Accession: `0001193125-26-111127`
  4. `LivePerson, Inc.` (SIC 7372 — Prepackaged Software; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1102993/000110299324000097/exhibit107-calculationoffi.htm](https://www.sec.gov/Archives/edgar/data/1102993/000110299324000097/exhibit107-calculationoffi.htm) / Accession: `0001102993-24-000097`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 107
Calculation of Filing Fee Tables
Form S-3
(Form Type)
Silk Road Medical, Inc.
(Exact Name of Registrant as Specified in its Charter)
Table 1: Newly Registered and Carry Forward Securities
Security Type | Security Class Title | Fee Calculation Rule | Amount Registered | Proposed Maximum Offering Price Per Unit | Maximum Aggregate Offering Price | Fee Rate | Amount of Registration Fee
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:Calculation\s+of\s+Filing\s+Fee\s+Tables?|EX-FILING\s+FEES|Exhibit\s+107 ) `
  - Disambiguation Rule: Formatted calculation table: `Table 1: Newly Registered and Carry Forward Securities`, structured columns (`Fee Calculation Rule`, `Amount Registered`, `Proposed Maximum Offering Price`, `Fee Rate`, `Amount of Registration Fee`), and statutory citations under `Rule 457` or `Rule 416`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Calculation\s+of\s+Filing\s+Fee\s+Tables?|EX-FILING\s+FEES)"
    r"[\s\S]{1,400}?(?:Newly\s+Registered|Fee\s+Calculation\s+Rule|Rule\s+457)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Older registration statement cover pages.
  - Mitigation: Modern SEC rules require filing fee tables to be filed as a separate exhibit (Exhibit 107 / EX-FILING FEES) with Inline XBRL tagging.

---

## PART III: TIER 3 — LOW PREVALENCE & SPECIALIZED DOMAIN FILINGS

### Tier 3 Overview Table

| Exhibit ID | Exhibit Title (Item 601) | Validated Link Count | Top Line Range | Primary Detection Prose Keywords | Secondary Disambiguation Tokens |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **EX-9** | Voting Trust Agreements | 4 | Lines 1–10 | `VOTING TRUST AGREEMENT`, `AMENDED & RESTATED VOTING TRUST AGREEMENT` | `Voting Trustees`, `Trust Certificates`, `deposit of shares of stock`, `transfer of record ownership` |
| **EX-13** | Annual or Quarterly Report to Security Holders | 4 | Lines 1–15 | `ANNUAL REPORT TO SECURITY HOLDERS`, `ANNUAL REPORT TO SHAREHOLDERS`, `LETTER TO SHAREHOLDERS` | `incorporated by reference`, `Financial Highlights`, `Management's Discussion`, `Form 10-K Part II` |
| **EX-20** | Other Documents or Statements to Security Holders | 4 | Lines 1–10 | `STATEMENT TO SECURITY HOLDERS`, `NOTICE TO SHAREHOLDERS`, `GENERAL PLAN`, `INFORMATION STATEMENT` | `distributed to shareholders`, `unitholders`, `royalty trust`, `monthly distribution` |
| **EX-31(ii)** | Rule 13a-14(d)/15d-14(d) Certifications (ABS) | 4 | Lines 1–12 | `Rule 13a-14(d)/15d-14(d) Certifications`, `I, [Name], certify that:`, `Exchange Act Periodic Reports` | `Form 10-D`, `Item 1123 of Regulation AB`, `servicer compliance statement`, `Item 1122 of Regulation AB`, `servicing criteria` |
| **EX-33** | Report on Assessment of Compliance with Servicing Criteria (ABS) | 4 | Lines 1–10 | `MANAGEMENT'S REPORT ON ASSESSMENT OF COMPLIANCE WITH APPLICABLE SERVICING CRITERIA`, `ITEM 1122` | `Item 1122(d) of Regulation AB`, `servicing criteria`, `Platform`, `asserting party`, `material instance of noncompliance` |
| **EX-34** | Attestation Report on Assessment of Compliance with Servicing Criteria | 4 | Lines 1–10 | `REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM`, `ATTESTATION REPORT ON ASSESSMENT OF COMPLIANCE` | `Item 1122(d) of Regulation AB`, `Standards for Attestation Engagements`, `AT-C Section 315`, `examination of management's assertion` |
| **EX-35** | Servicer Compliance Statement (ABS) | 4 | Lines 1–10 | `ANNUAL SERVICER COMPLIANCE STATEMENT`, `SERVICER COMPLIANCE STATEMENT PURSUANT TO ITEM 1123` | `Item 1123 of Regulation AB`, `Sale and Servicing Agreement`, `fulfilled its obligations under the servicing agreement` |
| **EX-36** | Certification for Shelf Offerings of Asset-Backed Securities | 4 | Lines 1–10 | `CERTIFICATION`, `Form SF-3`, `General Instruction I.B.1.(a)` | `securitized assets`, `structure of the securitization`, `expected cash flows at times and in amounts to service scheduled payments` |
| **EX-95** | Mine Safety Disclosure Exhibit | 4 | Lines 1–8 | `MINE SAFETY DISCLOSURE`, `MINE SAFETY DISCLOSURES` | `Section 1503(a) of the Dodd-Frank Act`, `Federal Mine Safety and Health Act of 1977`, `MSHA`, `Mine Safety and Health Administration` |
| **EX-96** | Technical Report Summary (Mining / Mineral Resources) | 4 | Lines 1–15 | `TECHNICAL REPORT SUMMARY`, `S-K 1300 TECHNICAL REPORT SUMMARY`, `INITIAL ASSESSMENT`, `FEASIBILITY STUDY` | `Regulation S-K Subpart 1300`, `Qualified Person`, `Mineral Resource Estimates`, `Mineral Reserve Estimates`, `Metallurgical Testing` |
| **EX-98** | Reports, Opinions, or Appraisals in de-SPAC Transactions | 4 | Lines 1–15 | `REPORT OF [FINANCIAL ADVISOR]`, `FAIRNESS OPINION`, `VALUATION APPRAISAL`, `ITEM 1607 OF REGULATION S-K` | `de-SPAC transaction`, `Business Combination Proposal`, `Subpart 1600 of Regulation S-K`, `fair, from a financial point of view` |
| **EX-102** | Asset Data File (ABS) | 4 | Lines 1–5 | `FORM ABS-EE`, `EX-102`, `Asset Data File` | `Item 1111(h)(3) of Regulation AB`, `17 CFR 229.601(b)(102)`, `<assetDataFile>`, `xml asset records` |
| **EX-103** | Asset Related Documents (ABS) | 4 | Lines 1–5 | `FORM ABS-EE`, `EX-103`, `Asset Related Document` | `Item 1111(h)(4) and (5) of Regulation AB`, `17 CFR 229.601(b)(103)`, `explanatory language`, `asset-level schedule` |
| **EX-106** | Static Pool Disclosure | 4 | Lines 1–10 | `STATIC POOL INFORMATION`, `STATIC POOL DISCLOSURE`, `STATIC POOL DATA` | `Item 1105 of Regulation AB`, `prior securitized pools`, `delinquencies, prepayments and cumulative net losses`, `Form SF-3` |

---

### Tier 3 Deep-Dive Profiles

#### EX-9 — Voting Trust Agreements
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(9)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `First Financial Northwest, Inc.` (SIC 6035; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1302215/000119312525337079/d58863dex91.htm](https://www.sec.gov/Archives/edgar/data/1302215/000119312525337079/d58863dex91.htm) / Accession: `0001193125-25-337079`
  2. `Wheels Up Experience Inc.` (SIC 4522; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1519622/000119312511261227/d184590dex91.htm](https://www.sec.gov/Archives/edgar/data/1519622/000119312511261227/d184590dex91.htm) / Accession: `0001193125-11-261227`
  3. `South Jersey Industries, Inc.` (SIC 4924; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/90168/000119312513047732/d452762dex91.htm](https://www.sec.gov/Archives/edgar/data/90168/000119312513047732/d452762dex91.htm) / Accession: `0001193125-13-047732`
  4. `Universal Forest Products, Inc.` (SIC 2421; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/912767/000091276704000010/ex9-1.htm](https://www.sec.gov/Archives/edgar/data/912767/000091276704000010/ex9-1.htm) / Accession: `0000912767-04-000010`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 9.1
DAY FAMILY
VOTING TRUST AGREEMENT
This Voting Trust Agreement (this “Agreement”), dated as of August 24, 2011, is entered into
by and among the shareholders of Wheels Up Experience Inc. whose names are set forth on the
signature pages hereto (each, a “Shareholder”), and John Day and Jane Day, as trustees
(collectively, the “Voting Trustees”).
WHEREAS, the Shareholders deem it to be in the best interest of the Company...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:AMENDED\s+AND\s+RESTATED\s+)?VOTING\s+TRUST\s+AGREEMENT `
  - Disambiguation Rule: Header contains `VOTING TRUST AGREEMENT`, followed on lines 4–15 by transfer of stock to named `Voting Trustees` and creation of `Voting Trust Certificates`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+9[\w.]*\s+)?[\w\s.,–—-]+? VOTING\s+TRUST\s+AGREEMENT [\s\S]{1,500}?"
    r"(?:Voting\s+Trustees?|Voting\s+Trust\s+Certificates?|deposit\s+of\s+shares\s+of\s+stock)",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: General stockholder voting agreements (EX-10).
  - Mitigation: Enforce presence of `Voting Trustees` and `Voting Trust Certificates`.

---

#### EX-13 — Annual or Quarterly Report to Security Holders
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(13)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Popular, Inc.` (SIC 6022; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/763901/000095014406002254/g00055exv13w1.htm](https://www.sec.gov/Archives/edgar/data/763901/000095014406002254/g00055exv13w1.htm) / Accession: `0000950144-06-002254`
  2. `Wintrust Financial Corp` (SIC 6022; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1015328/000101532814000073/exhibit131annualreporttosh.htm](https://www.sec.gov/Archives/edgar/data/1015328/000101532814000073/exhibit131annualreporttosh.htm) / Accession: `0001015328-14-000073`
  3. `Northwest Natural Gas Co` (SIC 4924; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/78128/000095012311018861/c13147exv13w1.htm](https://www.sec.gov/Archives/edgar/data/78128/000095012311018861/c13147exv13w1.htm) / Accession: `0000950123-11-018861`
  4. `South Jersey Industries, Inc.` (SIC 4924; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/90168/000009016815000012/exhibit131-annualreportto.htm](https://www.sec.gov/Archives/edgar/data/90168/000009016815000012/exhibit131-annualreportto.htm) / Accession: `0000090168-15-000012`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 13.1
ANNUAL REPORT TO SHAREHOLDERS
WINTRUST FINANCIAL CORPORATION
To Our Shareholders:
In 2013, Wintrust Financial Corporation achieved record net income of $143.9 million...
Our community banking philosophy continues to distinguish Wintrust from our competitors...
FINANCIAL HIGHLIGHTS
(In thousands, except per share data)
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:ANNUAL\s+REPORT\s+TO\s+(?:SECURITY\s+HOLDERS|SHAREHOLDERS|STOCKHOLDERS)|LETTER\s+TO\s+SHAREHOLDERS) `
  - Disambiguation Rule: Narrative letter to shareholders ("To Our Shareholders / Fellow Stockholders") and financial highlight summaries filed to satisfy Form 10-K Part II incorporation by reference under Rule 439.
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+13[\w.]*\s+)?[\w\s.,–—-]+? ANNUAL\s+REPORT\s+TO\s+(?:SHAREHOLDERS|SECURITY\s+HOLDERS|STOCKHOLDERS) "
    r"|To\s+Our\s+Shareholders[\s\S]{1,300}?(?:Financial\s+Highlights|Year\s+in\s+Review)",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: The primary Form 10-K report.
  - Mitigation: Form 10-K starts with `UNITED STATES SECURITIES AND EXCHANGE COMMISSION... FORM 10-K`; EX-13 is a standalone exhibit.

---

#### EX-20 — Other Documents or Statements to Security Holders
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(20)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Immunotech Laboratories, Inc.` (SIC 2834; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/1137117/000101738610000147/ex-20_1.htm](https://www.sec.gov/Archives/edgar/data/1137117/000101738610000147/ex-20_1.htm) / Accession: `0001017386-10-000147`
  2. `Forward Industries, Inc.` (SIC 3089; Non-Accelerated) — [https://www.sec.gov/Archives/edgar/data/38264/000114420414048281/v386121_ex20-1.htm](https://www.sec.gov/Archives/edgar/data/38264/000114420414048281/v386121_ex20-1.htm) / Accession: `0001144204-14-048281`
  3. `Cross Timbers Royalty Trust` (SIC 6792; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/881787/000088178721000014/cxt-20210331xex201.htm](https://www.sec.gov/Archives/edgar/data/881787/000088178721000014/cxt-20210331xex201.htm) / Accession: `0000881787-21-000014`
  4. `Sabine Royalty Trust` (SIC 6792; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/710752/000071075221000011/sbr-20210331xex201.htm](https://www.sec.gov/Archives/edgar/data/710752/000071075221000011/sbr-20210331xex201.htm) / Accession: `0000710752-21-000011`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 20.1
CROSS TIMBERS ROYALTY TRUST
MONTHLY DISTRIBUTION STATEMENT TO UNITHOLDERS
FOR THE MONTH OF MARCH 2021
Simmons Bank, as Trustee of Cross Timbers Royalty Trust, hereby furnishes this
Statement to Unitholders pursuant to the Trust Agreement...
Net Profits Income | Royalty Income | Distributable Amount
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:STATEMENT\s+TO\s+(?:SECURITY\s+HOLDERS|UNITHOLDERS|SHAREHOLDERS)|NOTICE\s+TO\s+SHAREHOLDERS|INFORMATION\s+STATEMENT\s+TO\s+SECURITY\s+HOLDERS) `
  - Disambiguation Rule: Non-proxy periodic distribution announcements or special notices distributed directly to unitholders or shareholders.
  - Suggested Regex / Logic:
```python
re.compile(
    r"^\s*(?:EXHIBIT\s+20[\w.]*\s+)?[\w\s.,–—-]+? (?:STATEMENT|NOTICE)\s+TO\s+(?:SECURITY\s+HOLDERS|UNITHOLDERS|SHAREHOLDERS) ",
    re.IGNORECASE | re.MULTILINE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Schedule 14A proxy materials.
  - Mitigation: Ensure document header does not contain `SCHEDULE 14A` or `PROXY STATEMENT`.

---

#### EX-31(ii) — Rule 13a-14(d)/15d-14(d) Certifications (ABS)
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(31)(ii)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `BMO 2025-5C9 Mortgage Trust` (SIC 6189 — Asset-Backed Securities) — [https://www.sec.gov/Archives/edgar/data/2048804/000188852426006154/bmo255c9_31.htm](https://www.sec.gov/Archives/edgar/data/2048804/000188852426006154/bmo255c9_31.htm) / Accession: `0001888524-26-006154`
  2. `Wells Fargo Commercial Mortgage Trust 2020-C56` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1803858/000188852426004565/wcm20c56_31.htm](https://www.sec.gov/Archives/edgar/data/1803858/000188852426004565/wcm20c56_31.htm) / Accession: `0001888524-26-004565`
  3. `BANK 2019-BNK19 Commercial Mortgage Trust` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1780859/000188852426004326/wcm19b19_31.htm](https://www.sec.gov/Archives/edgar/data/1780859/000188852426004326/wcm19b19_31.htm) / Accession: `0001888524-26-004326`
  4. `CarMax Auto Owner Trust 2025-2` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/2063979/000206397926000027/a2025-2ex311section302cert.htm](https://www.sec.gov/Archives/edgar/data/2063979/000206397926000027/a2025-2ex311section302cert.htm) / Accession: `0002063979-26-000027`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 31.1
I, Anthony Sfarra, certify that:
1. I have reviewed this report on Form 10-K and all reports on Form 10-D required to be filed
in respect of the period covered by this report on Form 10-K of BMO 2025-5C9 Mortgage Trust
(the “Exchange Act Periodic Reports”);
2. Based on my knowledge, the Exchange Act Periodic Reports, taken as a whole, do not contain
any untrue statement of a material fact...
3. Based on my knowledge, all of the distribution, servicing and other information required to be provided under Form 10-D...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) I,\s*[^,
]+,\s*certify\s+that:\s*
\s*1\.\s*I\s+have\s+reviewed\s+this\s+report\s+on\s+Form\s+10-K\s+and\s+all\s+reports\s+on\s+Form\s+10-D `
  - Disambiguation Rule: Explicitly pairs `Form 10-K` with `Form 10-D` ("the Exchange Act periodic reports"), Item 4 cites `Item 1123 of Regulation AB` (servicer compliance), and Item 5 cites `Item 1122 of Regulation AB` (servicing criteria).
  - Suggested Regex / Logic:
```python
re.compile(
    r"I,\s*[^,
]+,\s*certify\s+that:\s*1\.\s*I\s+have\s+reviewed\s+this\s+report\s+on\s+Form\s+10-K\s+and\s+all\s+reports\s+on\s+Form\s+10-D"
    r"[\s\S]{1,400}?Item\s+1123\s+of\s+Regulation\s+AB",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Standard corporate SOX 302 certifications (EX-31(i)).
  - Mitigation: EX-31(i) references rules 13a-15(e)/15d-15(e); EX-31(ii) strictly references `Form 10-D` and `Regulation AB`.

---

#### EX-33 — Report on Assessment of Compliance with Servicing Criteria for ABS
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(33) & 17 CFR § 229.1122(a) (Item 1122(a) of Regulation AB)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `KeyCorp Student Loan Trust 2006-A` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1380476/000095015207002893/l25386ae10vk.htm](https://www.sec.gov/Archives/edgar/data/1380476/000095015207002893/l25386ae10vk.htm) / Accession: `0000950152-07-002893`
  2. `GS Mortgage Securities Trust 2011-GC5` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1002761/000119312516519334/d120022dex331.htm](https://www.sec.gov/Archives/edgar/data/1002761/000119312516519334/d120022dex331.htm) / Accession: `0001193125-16-519334`
  3. `Benchmark 2019-B11 Mortgage Trust` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1780984/000119312522086423/d277600dex331.htm](https://www.sec.gov/Archives/edgar/data/1780984/000119312522086423/d277600dex331.htm) / Accession: `0001193125-22-086423`
  4. `Ally Auto Receivables Trust` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1379404/000119312511085149/dex331.htm](https://www.sec.gov/Archives/edgar/data/1379404/000119312511085149/dex331.htm) / Accession: `0001193125-11-085149`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 33.1
MANAGEMENT'S REPORT ON ASSESSMENT OF COMPLIANCE WITH APPLICABLE SERVICING CRITERIA
1. KeyBank National Association (the “Asserting Party”) is responsible for assessing compliance
with the servicing criteria applicable to it under paragraph (d) of Item 1122 of Regulation AB...
2. The Asserting Party has used the criteria in paragraph (d) of Item 1122 of Regulation AB
to assess the compliance with the applicable servicing criteria...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:REPORT\s+ON\s+ASSESSMENT\s+OF\s+COMPLIANCE\s+WITH\s+APPLICABLE\s+SERVICING\s+CRITERIA|MANAGEMENT['’]?S\s+REPORT\s+ON\s+ASSESSMENT\s+OF\s+COMPLIANCE|ASSERTION\s+OF\s+COMPLIANCE\s+WITH\s+REGULATION\s+AB\s+SERVICING\s+CRITERIA) `
  - Disambiguation Rule: Identifies the `Asserting Party`, references `Item 1122(d) of Regulation AB`, and asserts whether the platform had any `material instances of noncompliance`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:ASSESSMENT\s+OF\s+COMPLIANCE\s+WITH\s+(?:APPLICABLE\s+)?SERVICING\s+CRITERIA|Item\s+1122\s+Report)"
    r"[\s\S]{1,400}?(?:Item\s+1122(?:\(d\))?\s+of\s+Regulation\s+AB|Asserting\s+Party)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Independent auditor attestation reports (EX-34).
  - Mitigation: EX-33 is an internal assertion by the servicing institution (`Asserting Party`); EX-34 is an audit firm examination report.

---

#### EX-34 — Attestation Report on Assessment of Compliance with Servicing Criteria
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(34) & 17 CFR § 229.1122(b) (Item 1122(b) of Regulation AB)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Citigroup Commercial Mortgage Trust` (PricewaterhouseCoopers LLP) — [https://www.sec.gov/Archives/edgar/data/1174821/000119312521100051/d155301dex341.htm](https://www.sec.gov/Archives/edgar/data/1174821/000119312521100051/d155301dex341.htm) / Accession: `0001193125-21-100051`
  2. `Morgan Stanley Bank of America Merrill Lynch Trust` (Ernst & Young LLP) — [https://www.sec.gov/Archives/edgar/data/1405332/000119312526131067/d833533dex341.htm](https://www.sec.gov/Archives/edgar/data/1405332/000119312526131067/d833533dex341.htm) / Accession: `0001193125-26-131067`
  3. `Retail Properties of America ABS Trust` (KPMG LLP) — [https://www.sec.gov/Archives/edgar/data/1944485/000194448526000012/ex341retail2022-c2025.htm](https://www.sec.gov/Archives/edgar/data/1944485/000194448526000012/ex341retail2022-c2025.htm) / Accession: `0001944485-26-000012`
  4. `CarMax Auto Owner Trust` (KPMG LLP) — [https://www.sec.gov/Archives/edgar/data/2063979/000206397926000027/a2025-2ex341attestationrepo.htm](https://www.sec.gov/Archives/edgar/data/2063979/000206397926000027/a2025-2ex341attestationrepo.htm) / Accession: `0002063979-26-000027`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
Exhibit 34.1
REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM
To the Board of Directors of Morgan Stanley Capital I Inc.:
We have examined management's assertion, included in the accompanying Management's Report on Assessment
of Compliance with Applicable Servicing Criteria, that Morgan Stanley Mortgage Servicing complied with
the servicing criteria set forth in Item 1122(d) of the Securities and Exchange Commission's Regulation AB...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:ATTESTATION\s+REPORT\s+ON\s+ASSESSMENT\s+OF\s+COMPLIANCE|EXAMINATION\s+OF\s+MANAGEMENT['’]?S\s+ASSERTION\s+OF\s+COMPLIANCE\s+WITH\s+APPLICABLE\s+SERVICING\s+CRITERIA) `
  - Disambiguation Rule: Issued by a CPA firm; states `We have examined management's assertion... regarding compliance with the servicing criteria set forth in Item 1122(d) of Regulation AB`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"REPORT\s+OF\s+INDEPENDENT\s+(?:REGISTERED\s+PUBLIC\s+ACCOUNTING\s+FIRM|ACCOUNTANTS)"
    r"[\s\S]{1,400}?(?:examined\s+management['’]?s\s+assertion|examination\s+of\s+compliance\s+with\s+the\s+servicing\s+criteria)"
    r"[\s\S]{1,250}?Item\s+1122(?:\(d\))?",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Financial statement audit opinions.
  - Mitigation: Evaluates servicing criteria under `Item 1122(d) of Regulation AB`, not GAAP financial statements.

---

#### EX-35 — Servicer Compliance Statement
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(35) & 17 CFR § 229.1123 (Item 1123 of Regulation AB)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `CarMax Business Services, LLC` (CarMax Auto Owner Trust 2025-2) — [https://www.sec.gov/Archives/edgar/data/2063979/000206397926000027/a2025-2ex351servicercompli.htm](https://www.sec.gov/Archives/edgar/data/2063979/000206397926000027/a2025-2ex351servicercompli.htm) / Accession: `0002063979-26-000027`
  2. `Navient Solutions, LLC` (Navient Student Loan Trust) — [https://www.sec.gov/Archives/edgar/data/1582081/000114036125011391/ef20046227_ex35-1.htm](https://www.sec.gov/Archives/edgar/data/1582081/000114036125011391/ef20046227_ex35-1.htm) / Accession: `0001140361-25-011391`
  3. `Discover Bank` (Discover Card Execution Note Trust) — [https://www.sec.gov/Archives/edgar/data/894329/0001193125-24-259919-index.htm](https://www.sec.gov/Archives/edgar/data/894329/0001193125-24-259919-index.htm) / Accession: `0001193125-24-259919`
  4. `Ford Motor Credit Company LLC` (Ford Credit Auto Lease Trust) — [https://www.sec.gov/Archives/edgar/data/1519881/0001104659-25-049917-index.htm](https://www.sec.gov/Archives/edgar/data/1519881/0001104659-25-049917-index.htm) / Accession: `0001104659-25-049917`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EXHIBIT 35.1
ANNUAL SERVICER COMPLIANCE STATEMENT PURSUANT TO ITEM 1123 OF REGULATION AB
CARMAX BUSINESS SERVICES, LLC
The undersigned, a duly authorized officer of CarMax Business Services, LLC, as Servicer
pursuant to Section 3.10 of the Sale and Servicing Agreement... does hereby certify that:
1. A review of the activities of the Servicer... was made under my supervision; and
2. To the best of my knowledge, based on such review, the Servicer has fulfilled all of its
obligations under the Sale and Servicing Agreement in all material respects...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:ANNUAL\s+SERVICER\s+COMPLIANCE\s+STATEMENT|SERVICER\s+COMPLIANCE\s+STATEMENT\s+PURSUANT\s+TO\s+ITEM\s+1123) `
  - Disambiguation Rule: Officer certification confirming that a review was conducted and the servicer has `fulfilled all of its obligations under the [servicing agreement] in all material respects`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:SERVICER\s+COMPLIANCE\s+STATEMENT|Item\s+1123\s+of\s+Regulation\s+AB)[\s\S]{1,400}?"
    r"fulfilled\s+(?:all\s+of\s+)?its\s+obligations\s+under\s+the\s+(?:servicing|pooling\s+and\s+servicing|sale\s+and\s+servicing)\s+agreement",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Servicer distribution statements under Form 10-D.
  - Mitigation: EX-35 is a signed compliance certificate under Item 1123, not a numerical collection schedule.

---

#### EX-36 — Certification for Shelf Offerings of Asset-Backed Securities
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(36) & General Instruction I.B.1.(a) of Form SF-3
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `CarMax Auto Funding LLC` — [https://www.sec.gov/Archives/edgar/data/2117307/000119312526173263/d139274dex361.htm](https://www.sec.gov/Archives/edgar/data/2117307/000119312526173263/d139274dex361.htm) / Accession: `0001193125-26-173263`
  2. `American Express Receivables Financing Corp III LLC` — [https://www.sec.gov/Archives/edgar/data/1003509/000000000015052591/filename1.pdf](https://www.sec.gov/Archives/edgar/data/1003509/000000000015052591/filename1.pdf) / Accession: `0000000000-15-052591`
  3. `First National Funding LLC` — [https://www.sec.gov/Archives/edgar/data/1171040/000119312517128866/d347474d424b5.htm](https://www.sec.gov/Archives/edgar/data/1171040/000119312517128866/d347474d424b5.htm) / Accession: `0001193125-17-128866`
  4. `Synchrony Card Funding LLC` — [https://www.sec.gov/Archives/edgar/data/1724786/000110465921085135/tm2120345d1_sf3.htm](https://www.sec.gov/Archives/edgar/data/1724786/000110465921085135/tm2120345d1_sf3.htm) / Accession: `0001104659-21-085135`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EX-36.1
Certification
I, Enrique Mayor-Mora, certify as of April 21, 2026 that:
1. I have reviewed the prospectus relating to CarMax Auto Owner Trust 2026-1 (the “securities”)
and am familiar with, in all material respects, the following: The characteristics of the securitized
assets underlying the offering (the “securitized assets”), the structure of the securitization...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:CERTIFICATION\s+FOR\s+SHELF\s+OFFERINGS\s+OF\s+ASSET[- ]BACKED\s+SECURITIES|Form\s+SF-3\s+Certification) `
  - Disambiguation Rule: Item 4 specifies that `there is a reasonable basis to conclude that the securitization is structured to produce... expected cash flows at times and in amounts to service scheduled payments of interest and the ultimate repayment of principal`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"certify\s+as\s+of[\s\S]{1,300}?(?:securitized\s+assets|structure\s+of\s+the\s+securitization)[\s\S]{1,500}?"
    r"reasonable\s+basis\s+to\s+conclude\s+that\s+the\s+securitization\s+is\s+structured\s+to\s+produce",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Periodic Form 10-K ABS certifications (EX-31(ii)).
  - Mitigation: EX-36 is filed on Form SF-3 for shelf registrations; its operative trigger is paragraph 4 on debt service cash flow feasibility.

---

#### EX-95 — Mine Safety Disclosure Exhibit
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(95) & 17 CFR § 229.104 (Item 104 of Regulation S-K)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Alcoa Corporation` (SIC 3334; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1675149/000119312526326265/aa-ex95_1.htm](https://www.sec.gov/Archives/edgar/data/1675149/000119312526326265/aa-ex95_1.htm) / Accession: `0001193125-26-326265`
  2. `CONSOL Energy Inc.` (SIC 1220; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1718405/000171840526000020/exhibit951-minesafetydiscl.htm](https://www.sec.gov/Archives/edgar/data/1718405/000171840526000020/exhibit951-minesafetydiscl.htm) / Accession: `0001718405-26-000020`
  3. `Peabody Energy Corporation` (SIC 1221; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1064728/000106472825000014/btu-20241231.htm](https://www.sec.gov/Archives/edgar/data/1064728/000106472825000014/btu-20241231.htm) / Accession: `0001064728-25-000014`
  4. `Warrior Met Coal, Inc.` (SIC 1221; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1691303/000169130325000007/wcc-20241231.htm](https://www.sec.gov/Archives/edgar/data/1691303/000169130325000007/wcc-20241231.htm) / Accession: `0001691303-25-000007`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EXHIBIT 95.1
MINE SAFETY DISCLOSURE
Pursuant to Section 1503(a) of the Dodd-Frank Wall Street Reform and Consumer Protection Act
and Item 104 of Regulation S-K, each operator of a coal or other mine is required to disclose
in its periodic reports filed with the SEC information regarding specified health and safety
violations...
Mine Name / MSHA Identification Number | Section 104 S&S Citations | Section 104(b) Orders
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:MINE\s+SAFETY\s+DISCLOSURES?|DISCLOSURE\s+PURSUANT\s+TO\s+SECTION\s+1503(?:\(a\))?\s+OF\s+THE\s+DODD[- ]FRANK\s+ACT) `
  - Disambiguation Rule: Mentions `MSHA Identification Number`, `Federal Mine Safety and Health Act of 1977`, `Section 104 S&S citations`, `Section 107(a) orders`, or `mining-related fatalities`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:MINE\s+SAFETY\s+DISCLOSURE|Section\s+1503\(a\)\s+of\s+the\s+Dodd[- ]Frank)[\s\S]{1,400}?"
    r"(?:MSHA\s+Identification\s+Number|Federal\s+Mine\s+Safety\s+and\s+Health\s+Act|Section\s+104\s+S&S)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Form 10-K Item 4 text.
  - Mitigation: Form 10-K Item 4 incorporates by reference; Exhibit 95.1 provides the full tabular matrix.

---

#### EX-96 — Technical Report Summary (Mining / Mineral Resources)
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(96) & 17 CFR §§ 229.1300–1305 (Subpart 1300 of Regulation S-K)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Albemarle Corporation` (SIC 2821; Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/915913/000091591325000024/exhibit961greenbushes202.htm](https://www.sec.gov/Archives/edgar/data/915913/000091591325000024/exhibit961greenbushes202.htm) / Accession: `0000915913-25-000024`
  2. `Perpetua Resources Corp.` (SIC 1040; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1526243/000110465922069319/tm2217499d1_ex96-1.htm](https://www.sec.gov/Archives/edgar/data/1526243/000110465922069319/tm2217499d1_ex96-1.htm) / Accession: `0001104659-22-069319`
  3. `Gold Fields Limited` (SIC 1040; Foreign Large Accelerated) — [https://www.sec.gov/Archives/edgar/data/1172724/000117272425000010/a961-technicalreportsummar.htm](https://www.sec.gov/Archives/edgar/data/1172724/000117272425000010/a961-technicalreportsummar.htm) / Accession: `0001172724-25-000010`
  4. `Contango ORE, Inc.` (SIC 1040; Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1502377/000119312525117458/d90137dex961.htm](https://www.sec.gov/Archives/edgar/data/1502377/000119312525117458/d90137dex961.htm) / Accession: `0001193125-25-117458`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EX-96.1
Technical Report Summary
Greenbushes Mine, Western Australia
Albemarle Corporation
Prepared in accordance with Subpart 1300 of Regulation S-K
Qualified Persons:
Stantec Consulting Ltd. / SRK Consulting
1. Executive Summary
1.1 Property Description and Ownership...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:TECHNICAL\s+REPORT\s+SUMMARY|S-K\s+1300\s+TECHNICAL\s+REPORT\s+SUMMARY|SEC\s+TECHNICAL\s+REPORT\s+SUMMARY) `
  - Disambiguation Rule: Mandated 25-section format: includes `Qualified Person(s)`, `Mineral Resource Estimates`, `Mineral Reserve Estimates`, `Geological Setting and Mineralization`, and citation to `Subpart 1300 of Regulation S-K`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"TECHNICAL\s+REPORT\s+SUMMARY[\s\S]{1,500}?"
    r"(?:Subpart\s+1300|Qualified\s+Persons?|Mineral\s+Resources?\s+(?:and\s+Mineral\s+Reserves?\s+)?Estimates?)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: Canadian NI 43-101 technical reports filed on Form 6-K.
  - Mitigation: Require explicit references to `Regulation S-K Subpart 1300` / `Item 601(b)(96)`.

---

#### EX-98 — Reports, Opinions, or Appraisals in de-SPAC Transactions
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(98) & 17 CFR § 229.1607(c) (Item 1607(c) of Regulation S-K)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `IX Acquisition Corp.` (SIC 6770; Non-Accelerated Filer) — [https://www.sec.gov/Archives/edgar/data/1852019/000110465924103820/ixaqu-20240630xex98d1.htm](https://www.sec.gov/Archives/edgar/data/1852019/000110465924103820/ixaqu-20240630xex98d1.htm) / Accession: `0001104659-24-103820`
  2. `Hall Chadwick Acquisition Corp.` (SIC 6770; Form S-4) — [https://www.sec.gov/Archives/edgar/data/2079013/000182912626010648/hallchadwickacq_s4.htm](https://www.sec.gov/Archives/edgar/data/2079013/000182912626010648/hallchadwickacq_s4.htm) / Accession: `0001829126-26-010648`
  3. `Relativity Acquisition Corp.` (SIC 6770; Form S-4) — [https://www.sec.gov/Archives/edgar/data/2072188/000000000025009167/filename1.pdf](https://www.sec.gov/Archives/edgar/data/2072188/000000000025009167/filename1.pdf) / Accession: `0000000000-25-009167`
  4. `Welsbach Technology Metals Acquisition Corp.` (SIC 6770; Form S-4) — [https://www.sec.gov/Archives/edgar/data/2043020/000000000024013586/filename1.pdf](https://www.sec.gov/Archives/edgar/data/2043020/000000000024013586/filename1.pdf) / Accession: `0000000000-24-013586`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EX-98.1
STRICTLY CONFIDENTIAL
Board of Directors
IX Acquisition Corp.
Gentlemen:
You have requested our opinion as to the fairness, from a financial point of view, to IX Acquisition Corp.
of the consideration to be paid in connection with the proposed de-SPAC business combination...
pursuant to Item 1607 of Regulation S-K...
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:REPORT\s+PURSUANT\s+TO\s+ITEM\s+1607|OPINION\s+IN\s+DE[- ]SPAC\s+TRANSACTION|FAIRNESS\s+OPINION[\s\S]{1,100}?de[- ]SPAC) `
  - Disambiguation Rule: Fairness opinion, board appraisal, or third-party financial valuation explicitly rendered in connection with a `de-SPAC transaction` pursuant to `Item 1607(c) of Regulation S-K`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Item\s+1607(?:\(c\))?|de[- ]SPAC\s+(?:transaction|business\s+combination))[\s\S]{1,500}?"
    r"(?:fairness\s+opinion|opinion\s+as\s+to\s+(?:the\s+)?fairness|financial\s+point\s+of\s+view|appraisal)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: M&A fairness opinions attached as annexes to Form S-4 or Schedule 14A.
  - Mitigation: EX-98 is specifically coded as an exhibit to the registration statement under Item 601(b)(98).

---

#### EX-102 — Asset Data File
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(102) & 17 CFR § 229.1111(h)(3) (Item 1111(h)(3) of Regulation AB)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `DRIVE Auto Receivables Trust` (Form ABS-EE) — [https://www.sec.gov/Archives/edgar/data/1752363/000188852426003320/dma18001_absee-202602.htm](https://www.sec.gov/Archives/edgar/data/1752363/000188852426003320/dma18001_absee-202602.htm) / Accession: `0001888524-26-003320`
  2. `Morgan Stanley Capital I Inc.` (Form ABS-EE) — [https://www.sec.gov/Archives/edgar/data/1769961/000188852422001217/msc19b17_absee-202201.htm](https://www.sec.gov/Archives/edgar/data/1769961/000188852422001217/msc19b17_absee-202201.htm) / Accession: `0001888524-22-001217`
  3. `Goldman Sachs Mortgage Securities Trust` (Form ABS-EE) — [https://www.sec.gov/Archives/edgar/data/0001895116/000188852426002559/gsm21gs3_absee-202602.htm](https://www.sec.gov/Archives/edgar/data/0001895116/000188852426002559/gsm21gs3_absee-202602.htm) / Accession: `0001888524-26-002559`
  4. `Deutsche Bank Commercial Mortgage Trust` (Form ABS-EE) — [https://www.sec.gov/Archives/edgar/data/0001706403/000188852426017117/dbj17c06_absee-202609.htm](https://www.sec.gov/Archives/edgar/data/0001706403/000188852426017117/dbj17c06_absee-202609.htm) / Accession: `0001888524-26-017117`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
FORM FOR SUBMISSION OF ELECTRONIC EXHIBITS FOR ASSET-BACKED SECURITIES
FORM ABS-EE
Item 1. File an Asset Data File in accordance with Exhibit 601(b)(102) (17 CFR 229.601(b)(102)).
Item 2. File an Asset Related Document in accordance with Exhibit 601(b)(103) (17 CFR 229.601(b)(103)).
Name of Issuing Entity: DRIVE Auto Receivables Trust 2018-1
Name of Depositor: Santander Consumer USA Inc.
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:Asset\s+Data\s+File|EX-102|Exhibit\s+601\(b\)\(102\)|<assetDataFile>) `
  - Disambiguation Rule: Form ABS-EE filings and Item 1111(h)(3); raw XML file features schema namespace `http://www.sec.gov/edgar/abs/assetdata` or `<assetData>`.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Asset\s+Data\s+File\s+in\s+accordance\s+with\s+Exhibit\s+(?:601\(b\)\()?102\)?|"
    r"xmlns=["']http://www\.sec\.gov/edgar/abs/assetdata["']|EX-102 )",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: EX-101 Interactive Data Files (corporate XBRL).
  - Mitigation: EX-101 files use standard GAAP/IFRS taxonomies; EX-102 files use the SEC Asset-Backed Securitization XML schema.

---

#### EX-103 — Asset Related Documents
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(103) & 17 CFR § 229.1111(h)(4)/(5) (Item 1111(h)(4) & (5) of Regulation AB)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Deutsche Bank Commercial Mortgage Trust` — [https://www.sec.gov/Archives/edgar/data/0001706403/000188852426017117/dbj17c06_absee-202609.htm](https://www.sec.gov/Archives/edgar/data/0001706403/000188852426017117/dbj17c06_absee-202609.htm) / Accession: `0001888524-26-017117`
  2. `DRIVE Auto Receivables Trust` — [https://www.sec.gov/Archives/edgar/data/1818254/000105640420011205/dma20c09_absee-202009.htm](https://www.sec.gov/Archives/edgar/data/1818254/000105640420011205/dma20c09_absee-202009.htm) / Accession: `0001056404-20-011205`
  3. `Morgan Stanley Capital I Inc.` — [https://www.sec.gov/Archives/edgar/data/1769961/000188852422001217/msc19b17_absee-202201.htm](https://www.sec.gov/Archives/edgar/data/1769961/000188852422001217/msc19b17_absee-202201.htm) / Accession: `0001888524-22-001217`
  4. `Goldman Sachs Mortgage Securities Trust` — [https://www.sec.gov/Archives/edgar/data/0001895116/000188852426002559/gsm21gs3_absee-202602.htm](https://www.sec.gov/Archives/edgar/data/0001895116/000188852426002559/gsm21gs3_absee-202602.htm) / Accession: `0001888524-26-002559`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EX-103
Asset Related Document
Item 2. File an Asset Related Document in accordance with Exhibit 601(b)(103) (17 CFR 229.601(b)(103))
Additional Explanatory Language and Code Dictionary for Asset Data File
Table of Field Definitions and Servicer Data Limitations
Field Name | Description | Calculation Methodology
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:Asset\s+Related\s+Document|EX-103|Exhibit\s+601\(b\)\(103\)) `
  - Disambiguation Rule: Explanatory narrative schedule attached to Form ABS-EE detailing data limitations or field code dictionaries under Item 1111(h)(4) and (5).
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:Asset\s+Related\s+Document\s+in\s+accordance\s+with\s+Exhibit\s+(?:601\(b\)\()?103\)?|"
    r"EX-103 [\s\S]{1,250}?Item\s+1111\(h\)\([45]\))",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: EX-102 Asset Data File.
  - Mitigation: EX-102 is the raw machine-readable XML asset schedule; EX-103 is human-readable explanatory documentation/metadata.

---

#### EX-106 — Static Pool Disclosure
- **Regulation S-K Citation**: 17 CFR § 229.601(b)(106) & 17 CFR § 229.1105 (Item 1105 of Regulation AB)
- **Evidence Sources (Inspected EDGAR Links)**:
  1. `Discover Card Master Trust I` (SIC 6189 — Asset-Backed Securities) — [https://www.sec.gov/Archives/edgar/data/894329/0001193125-24-259919-index.htm](https://www.sec.gov/Archives/edgar/data/894329/0001193125-24-259919-index.htm) / Accession: `0001193125-24-259919`
  2. `Ford Credit Auto Lease Two LLC` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1519881/0001104659-25-049917-index.htm](https://www.sec.gov/Archives/edgar/data/1519881/0001104659-25-049917-index.htm) / Accession: `0001104659-25-049917`
  3. `CarMax Auto Funding LLC` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1631030/0001193125-25-091479-index.htm](https://www.sec.gov/Archives/edgar/data/1631030/0001193125-25-091479-index.htm) / Accession: `0001193125-25-091479`
  4. `Honda Auto Receivables Owner Trust` (SIC 6189 — ABS) — [https://www.sec.gov/Archives/edgar/data/1136586/0000929638-25-001041-index.htm](https://www.sec.gov/Archives/edgar/data/1136586/0000929638-25-001041-index.htm) / Accession: `0000929638-25-001041`
- **Raw Prose Snippet (First 5–10 Lines of Tag-Free Text)**:
```text
EX-106
STATIC POOL INFORMATION
Item 1105 of Regulation AB
Historical Performance of Prior Securitized Pools
CarMax Auto Owner Trusts
Vintage Origination Year: 2021 - 2025
Pool Factor | Cumulative Net Loss Rate | 30-Day Delinquency Rate | 60-Day Delinquency Rate
```
- **Proposed Prose Heuristic**:
  - Primary Anchors: `(?i) (?:STATIC\s+POOL\s+(?:INFORMATION|DISCLOSURE|DATA)|Item\s+1105\s+of\s+Regulation\s+AB) `
  - Disambiguation Rule: Historical multi-vintage securitization performance schedule covering `cumulative net losses`, `prepayments`, and `delinquencies` across prior trusts of the sponsor/depositor.
  - Suggested Regex / Logic:
```python
re.compile(
    r"(?:STATIC\s+POOL\s+(?:INFORMATION|DISCLOSURE|DATA)|EX-106 )[\s\S]{1,400}?"
    r"(?:Item\s+1105\s+of\s+Regulation\s+AB|prior\s+securitized\s+pools|cumulative\s+net\s+losses)",
    re.IGNORECASE
)
```
- **False Positive / Negative Analysis**:
  - False Positives: In-prospectus static pool disclosures filed under Rule 424(b).
  - Mitigation: Standalone exhibit filed under Item 601(b)(106) is designated `Exhibit 106` / `EX-106`.

---

## PART IV: APPENDIX — RESERVED AND OBSOLETE ITEM 601 EXHIBIT NUMBERS

Pursuant to 17 CFR § 229.601, the following exhibit numbers are officially designated as **[Reserved]** by the Securities and Exchange Commission:
- **Exhibit (6)**: [Reserved]
- **Exhibits (11) and (12)**: [Reserved] (Formerly: Computation of per share earnings; Computation of ratios)
- **Exhibits (26) through (30)**: [Reserved]
- **Exhibits (37) through (94)**: [Reserved]
- **Exhibit (100)**: [Reserved]
- **Exhibit (105)**: [Reserved]

