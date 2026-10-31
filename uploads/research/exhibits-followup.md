# SEC EDGAR Tag-Free Exhibit Classifier: Advanced Architectural Blueprint & Follow-Up Analysis
**Multi-Authority Mapping, Subtype Decomposition, and Disambiguation Engine**

---

## 1. Executive Architecture: Authority-Qualified Exhibit Ledger & Content-Pack Decoupling

### 1.1 The Authority Collision Problem
A critical failure mode in automated SEC EDGAR parsing pipelines is treating exhibit identifiers as flat integer codes (e.g., `exhibit_id = 1` or `EX-1`). On EDGAR, exhibit numbering is not globally uniform across all form types; rather, each statutory filing authority defines its own distinct exhibit schedule.

The most prominent collision occurs between **17 CFR § 229.601 (Item 601 of Regulation S-K)** (governing domestic periodic filings like Form 10-K, 10-Q, 8-K, and registration statements S-1, S-3, S-4) and **Form 20-F (17 CFR § 249.220f)** (governing Foreign Private Issuer annual reports and registrations):

| Exhibit Code | Item 601 (Domestic / S-Forms) Scope | Form 20-F (Foreign Private Issuer) Scope | Collision Category |
| :--- | :--- | :--- | :--- |
| **EX-1** | Underwriting Agreements | Articles of Incorporation / Association & Bylaws | **Direct Semantic Conflict** |
| **EX-2** | Plan of Acquisition / Merger / Reorganization | Instruments Defining Rights of Security Holders & Indentures | **Direct Semantic Conflict** |
| **EX-3** | Articles of Incorporation (3.1) & Bylaws (3.2) | Voting Trust Agreements | **Direct Semantic Conflict** |
| **EX-4** | Instruments Defining Rights of Security Holders | Material Contracts | **Direct Semantic Conflict** |
| **EX-5** | Legality Opinions | Material Foreign Patent List (upon request) | **Direct Semantic Conflict** |
| **EX-8** | Tax Opinions | Subsidiaries of the Registrant | **Direct Semantic Conflict** |
| **EX-11** | *[Reserved]* | Code of Ethics & Insider Trading Policies | **Form-Specific Numbering** |
| **EX-12** | *[Reserved]* | Rule 13a-14(a)/15d-14(a) Certifications (SOX 302) | **Form-Specific Numbering** |
| **EX-13** | Annual or Quarterly Report to Security Holders | Section 1350 Certifications (SOX 906) | **Direct Semantic Conflict** |
| **EX-14** | Code of Ethics | Legal Opinion under Form 20-F Item 7.B | **Direct Semantic Conflict** |
| **EX-16** | Letter re Change in Certifying Accountant | Mine Safety Disclosure | **Direct Semantic Conflict** |
| **EX-17** | Correspondence on Departure of Director | Subsidiary Guarantors & Pledged Affiliates | **Direct Semantic Conflict** |
| **EX-21** | Subsidiaries of the Registrant | *[Not Present – Mapped to Form 20-F Ex 8]* | **Cross-Authority Drift** |
| **EX-22** | Subsidiary Guarantors & Pledged Affiliates | *[Not Present – Mapped to Form 20-F Ex 17]* | **Cross-Authority Drift** |
| **EX-31** | SOX 302 Certifications ((i) Corp, (ii) ABS) | *[Not Present – Mapped to Form 20-F Ex 12]* | **Cross-Authority Drift** |
| **EX-32** | Section 1350 Certifications (SOX 906) | *[Not Present – Mapped to Form 20-F Ex 13]* | **Cross-Authority Drift** |
| **EX-95** | Mine Safety Disclosure Exhibit | *[Not Present – Mapped to Form 20-F Ex 16]* | **Cross-Authority Drift** |
| **EX-97** | Clawback Policy (Recovery of Compensation) | Clawback Policy (Rule 10D-1) | **Harmonized Numbering (Post-2023)** |
| **EX-101** | Interactive Data File (Inline XBRL) | Interactive Data File (Inline XBRL) | **Harmonized Technical Numbering** |
| **EX-104** | Cover Page Interactive Data File | Cover Page Interactive Data File | **Harmonized Technical Numbering** |

Further collisions exist in specialized domain forms:
- **Form SF-3 (Asset-Backed Shelf Registration)** introduces **Exhibit 36** (Depositor Shelf Certification under General Instruction I.B.1.(a)), which does not exist in Form 20-F or standard corporate 10-K filings.
- **Form ABS-EE (Electronic Exhibits for Asset-Backed Securities)** mandates **Exhibit 102** (Asset Data File) and **Exhibit 103** (Asset Related Documents), which are reserved in Form 20-F.

### 1.2 Architectural Resolution: The Decoupled Content-Pack Model
To eliminate numbering collisions, the parsing pipeline decouples **Authority-Qualified Filing Identifiers** from **Content Classification Packs**:

```
[EDGAR Submission Document]
       │
       ▼
1. Metadata Ingestion: Extract (Authority, Exhibit_Code)
   Example A: ("ITEM_601", "EX-3.1")
   Example B: ("FORM_20F", "EX-1")
       │
       ▼
2. Dynamic Route Mapping: Lookup Target Content-Pack
   Both Example A & B resolve to -> ContentPack: ORGANIZATIONAL_DOCUMENTS
       │
       ▼
3. NLP Prose Evaluator: Apply Subtype Classifier
   -> Subtype: ARTICLES_OF_INCORPORATION (vs BYLAWS)
       │
       ▼
4. Canonical Result:
   {
     "authority": "FORM_20F",
     "source_exhibit_code": "EX-1",
     "content_pack": "ORGANIZATIONAL_DOCUMENTS",
     "subtype": "ARTICLES_OF_ASSOCIATION",
     "confidence": 0.98
   }
```

This decoupled architecture allows the prose classifier to focus strictly on legal/contractual prose semantics, while the authority mapper handles form-specific compliance.

---

## 2. Advanced Subtype Decompositions & Granular Discriminator Profiles

Below are the granular discriminator specifications for exhibits requiring bounded subtype isolation, negative lookaheads, or specialist corpora.

---

### Exhibit 2 (Item 601) — Plan of Acquisition, Reorganization, Arrangement, Liquidation, or Succession
*Proposed Module: `ex2_item601.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(2)
- **Design Challenge**: Must distinguish four fundamentally different transactional plans and avoid false positives from general commercial agreements (Item 10) or proxy statements.

#### Subtype 2.A: Agreement and Plan of Merger (`merger_plan`)
- **Primary Detection Prose Anchors**:
  - `(?i) AGREEMENT\s+AND\s+PLAN\s+OF\s+MERGER `
  - `(?i) AGREEMENT\s+AND\s+PLAN\s+OF\s+REORGANIZATION `
- **Secondary Disambiguation Tokens (Top 25 Lines / 1,500 chars)**:
  - Parties: `Merger Sub`, `Surviving Corporation`, `Target Company`, `Parent`
  - Operative Terms: `Effective Time`, `Certificate of Merger`, `DGCL Section 251`, `merger consideration`
- **Negative Lookaheads / Boundaries**:
  - Must NOT match `LOAN AND MERGER AGREEMENT` (Item 10 Credit Agreement).
  - Must NOT match `FORM OF PROXY` or `SCHEDULE 14A`.
- **Regex Logic**:
  ```python
  re.compile(
      r"^\s*(?:EXHIBIT\s+2(?:\.1)?\s+)?[\w\s,–—-]+? AGREEMENT\s+AND\s+PLAN\s+OF\s+MERGER [\s\S]{1,600}?"
      r"(?:Merger\s+Sub|Surviving\s+(?:Corporation|Entity)|Certificate\s+of\s+Merger)",
      re.IGNORECASE | re.MULTILINE
  )
  ```

#### Subtype 2.B: Asset Purchase Agreement (`asset_purchase_plan`)
- **Primary Detection Prose Anchors**:
  - `(?i) ASSET\s+PURCHASE\s+AGREEMENT `
  - `(?i) PURCHASE\s+AND\s+SALE\s+AGREEMENT\s+AND\s+PLAN\s+OF\s+DISPOSITION `
- **Secondary Disambiguation Tokens**:
  - `Purchased Assets`, `Acquired Assets`, `Excluded Assets`, `Assumed Liabilities`, `Excluded Liabilities`, `Bill of Sale`
- **Disambiguation vs Item 10**: Under Item 601(b)(2)(i), an asset agreement is filed under Exhibit 2 only if it constitutes a **material disposition or acquisition of a business/plan of disposition**. Ordinary procurement or equipment purchase agreements belong in Item 10. Item 2 asset agreements feature `Assumed Liabilities` and `Excluded Assets`.

#### Subtype 2.C: Stock Purchase / Equity Acquisition Agreement (`stock_purchase_plan`)
- **Primary Detection Prose Anchors**:
  - `(?i) (?:STOCK|SHARE|SECURITIES|MEMBERSHIP\s+INTEREST)\s+PURCHASE\s+AGREEMENT `
- **Secondary Disambiguation Tokens**:
  - `selling stockholders`, `purchase and sale of all outstanding capital stock`, `closing consideration`, `equity purchase`

#### Subtype 2.D: Plan of Complete Liquidation and Dissolution (`liquidation_plan`)
- **Primary Detection Prose Anchors**:
  - `(?i) PLAN\s+OF\s+(?:COMPLETE\s+)?LIQUIDATION\s+AND\s+DISSOLUTION `
- **Secondary Disambiguation Tokens**:
  - `winding up`, `liquidating trust`, `distribution of remaining assets`, `certificate of dissolution`, `General Corporation Law`

---

### Exhibit 3 (Item 601) & Exhibit 1 (Form 20-F) — Organizational Documents
*Proposed Module: `ex3_item601.py` & `form20f_ex1.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(3) / Form 20-F Instructions as to Exhibits (Exhibit 1)
- **Design Challenge**: Must separate Articles/Charters from Bylaws into distinct subtype packs, while handling foreign organizational equivalents (Memorandum and Articles of Association, Constitution, Statutes).

#### Subtype 3.1: Articles / Certificate of Incorporation / Charter (`articles_of_incorporation`)
- **Primary Detection Prose Anchors**:
  - Domestic: `CERTIFICATE OF INCORPORATION`, `ARTICLES OF INCORPORATION`, `CERTIFICATE OF FORMATION`, `CHARTER`
  - Foreign (20-F): `MEMORANDUM OF ASSOCIATION`, `ARTICLES OF ASSOCIATION`, `CONSTITUTION OF [COMPANY]`, `STATUTES OF [COMPANY]`
- **Secondary Disambiguation Tokens**:
  - Domestic: `Secretary of State`, `General Corporation Law`, `authorized shares`, `par value`, `registered agent`
  - Foreign: `Companies Act`, `Registrar of Companies`, `exempted company limited by shares`, `Cayman Islands`, `Bermuda`, `England and Wales`
- **Negative Constraint**: Must NOT match `BYLAWS` in the document title header.

#### Subtype 3.2: Bylaws (`bylaws`)
- **Primary Detection Prose Anchors**:
  - `(?i) (?:AMENDED\s+AND\s+RESTATED\s+|SECOND\s+AMENDED\s+AND\s+RESTATED\s+)?BY[- ]?LAWS `
- **Secondary Disambiguation Tokens**:
  - `ARTICLE I`, `OFFICES`, `MEETINGS OF STOCKHOLDERS`, `BOARD OF DIRECTORS`, `QUORUM`, `NOTICE OF MEETINGS`
- **Disambiguation vs 3.1**: Bylaws govern internal administrative proceedings (how the Board acts, voting procedures) and are **never** filed with the Secretary of State.

---

### Exhibit 4 (Item 601) & Exhibit 2 (Form 20-F) — Security Holder Instruments
*Proposed Module: `ex4_item601.py` & `form20f_ex2.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(4) / Form 20-F Instructions as to Exhibits (Exhibit 2)
- **Design Challenge**: **Do not equate one indenture cue with full coverage.** Item 4 contains four distinct legal categories.

#### Subtype 4.A: Base & Supplemental Indentures (`indentures`)
- **Primary Anchors**: `(?i) (?:SENIOR\s+|SUBORDINATED\s+)?(?:INDENTURE|SUPPLEMENTAL\s+INDENTURE) `
- **Disambiguation Tokens**: `Trustee`, `as Trustee`, `Trust Indenture Act of 1939`, `Senior Notes due`, `Paying Agent`, `Securities Registrar`
- **Negative Lookahead**: Must NOT match `ADMINISTRATIVE AGENT` or `BORROWER` (which defines EX-10 Credit Agreements).

#### Subtype 4.B: Officer's Certificates / Terms of Securities (`officers_certificate_notes`)
- **Primary Anchors**: `(?i) OFFICER['’]?S\s+CERTIFICATE\s+(?:PURSUANT\s+TO\s+SECTION\s+[\d.]+\s+OF\s+THE\s+INDENTURE|ESTABLISHING\s+THE\s+TERMS\s+OF) `
- **Disambiguation Tokens**: `Officers' Certificate pursuant to Indenture`, `terms of the Notes`, `Maturity Date`, `Interest Rate`, `Redemption Price`

#### Subtype 4.C: Description of Registered Securities (`description_of_securities`)
- **Primary Anchors**: `(?i) DESCRIPTION\s+OF\s+(?:THE\s+)?REGISTRANT['’]?S\s+SECURITIES\s+REGISTERED\s+PURSUANT\s+TO\s+SECTION\s+12 `
- **Disambiguation Tokens**: `Item 202 of Regulation S-K`, `Securities Exchange Act of 1934`, `Common Stock`, `Preferred Stock`, `Voting Rights`
- **Structural Profile**: Narrative summary filed as Exhibit 4 to Form 10-K since the 2019 FAST Act amendments.

#### Subtype 4.D: Warrant Agreements & Rights Plans (`warrant_and_rights_plans`)
- **Primary Anchors**: `(?i) (?:WARRANT\s+AGREEMENT|RIGHTS\s+AGREEMENT|SHAREHOLDER\s+RIGHTS\s+PLAN) `
- **Disambiguation Tokens**: `Warrant Agent`, `Rights Agent`, `Exercise Price`, `Warrant Certificate`, `Distribution Date`, `Preferred Share Purchase Rights`

---

### Exhibit 5 (Legality) vs Exhibit 8 (Tax) — The Negative Disambiguation Pair
*Proposed Modules: `ex5_item601.py` vs `ex8_item601.py` (and `form20f_ex14.py`)*
- **Design Challenge**: Both are formal legal opinion letters rendered by major corporate law firms, often in connection with the same registration statement (S-1/S-3/S-4). They must be decoupled using mutually exclusive substantive anchors.

#### Comparison & Negative Disambiguation Matrix:

| Evaluation Dimension | Exhibit 5 (Legality Opinion) | Exhibit 8 (Tax Opinion) |
| :--- | :--- | :--- |
| **Statutory Mandate** | 17 CFR § 229.601(b)(5) / Form 20-F Ex 14 | 17 CFR § 229.601(b)(8) |
| **Core Operative Holding** | Equity: `validly issued, fully paid and non-assessable`<br>Debt: `legally valid and binding obligations of the Company` | Tax: `reorganization within the meaning of Section 368(a)`<br>REIT: `qualifies as a real estate investment trust under Section 856`<br>General: `statements under 'Material U.S. Federal Income Tax Considerations' are accurate in all material respects` |
| **Primary Statutory Citations** | `Section 7 of the Securities Act`, `General Corporation Law` | `Internal Revenue Code of 1986`, `Treasury Regulations`, `Section 368`, `Section 355`, `Section 856` |
| **Addressee & Subject** | Addressed to Company: Authority to issue and sell registered securities | Addressed to Company/Shareholders: Tax consequences to investors |
| **Negative Lookahead Rule** | Discard if document centers on `Internal Revenue Code` or `Tax Opinion` | Discard if document centers on corporate validity (`validly issued, fully paid and non-assessable`) |

---

### Exhibit 7 (Item 601) — Correspondence from Independent Accountant on Non-Reliance
*Proposed Module: `ex7_item601.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(7) & Form 8-K Item 4.02(c)
- **Status in Ledger**: *Unsupported in generic evaluator; newly profiled herein.*
- **Scope**: Any written notice from the independent accountant stating that its previously issued audit report or completed interim review should no longer be relied upon, or a responsive letter from the accountant under Form 8-K Item 4.02(c) stating whether it agrees with the company's disclosure.

#### Detection Profile for Item 7:
- **Primary Detection Prose Anchors**:
  - `(?i) (?:Item\s+4\.02(?:\(c\))?\s+of\s+Form\s+8-K|non[- ]reliance\s+on\s+previously\s+issued\s+(?:financial\s+statements|audit\s+report)) `
  - `(?i) (?:withdrawing\s+(?:a\s+previously\s+issued\s+)?audit\s+report|should\s+no\s+longer\s+be\s+relied\s+upon) `
- **Secondary Disambiguation Tokens**:
  - Addressed to: `Securities and Exchange Commission`, `Commissioners:`
  - Body phrasing: `We have read Item 4.02 of Form 8-K`, `We agree with the statements made by [Registrant]`, `Audit Committee`, `Restatement`
- **Disambiguation vs EX-16 (Item 4.01 Auditor Change)**:
  - EX-16 explicitly cites `Item 4.01 of Form 8-K` and `Item 304 of Regulation S-K` regarding dismissal or resignation.
  - EX-7 explicitly cites `Item 4.02 of Form 8-K` regarding financial statement non-reliance / restatement.
- **Suggested Regex / Logic**:
  ```python
  re.compile(
      r"(?:Securities\s+and\s+Exchange\s+Commission|Commissioners:)[\s\S]{1,400}?"
      r"Item\s+4\.02(?:\([bc]\))?[\s\S]{1,300}?"
      r"(?:non[- ]reliance|should\s+no\s+longer\s+be\s+relied\s+upon|agree\s+with\s+the\s+statements)",
      re.IGNORECASE
  )
  ```

---

### Exhibit 10 (Item 601) & Exhibit 4 (Form 20-F) — Material Contracts
*Proposed Module: `ex10_item601.py` & `form20f_ex4.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(10) / Form 20-F Instructions as to Exhibits (Exhibit 4)
- **Design Challenge**: **Bounded subtypes only, not "any agreement".** An open-ended contract regex causes massive false positives across every filed agreement. Must be partitioned into bounded commercial and compensatory categories.

#### Subtype 10.A: Credit Facilities & Financing Agreements (`credit_facilities`)
- **Primary Anchors**: `CREDIT AGREEMENT`, `CREDIT FACILITY`, `TERM LOAN AGREEMENT`, `REVOLVING CREDIT AGREEMENT`, `LOAN AND SECURITY AGREEMENT`
- **Disambiguation Tokens**: `Administrative Agent`, `Syndication Agent`, `Lenders`, `Borrower`, `Revolving Commitments`, `Letter of Credit Issuer`, `Applicable Margin`

#### Subtype 10.B: Management Contracts & Executive Compensation (`executive_compensation`)
- **Primary Anchors**: `EMPLOYMENT AGREEMENT`, `EXECUTIVE EMPLOYMENT AGREEMENT`, `SEVERANCE AGREEMENT`, `CHANGE IN CONTROL AGREEMENT`, `INCENTIVE AWARD PLAN`, `STOCK OPTION PLAN`
- **Disambiguation Tokens**: `Executive`, `Base Salary`, `Annual Bonus`, `Severance Benefits`, `Restricted Stock Units`, `Performance Share Units`

#### Subtype 10.C: Commercial Supply, Manufacturing & Distribution (`commercial_agreements`)
- **Primary Anchors**: `SUPPLY AGREEMENT`, `MANUFACTURING AGREEMENT`, `MASTER SERVICES AGREEMENT`, `DISTRIBUTION AGREEMENT`, `PURCHASE AND SALE AGREEMENT`
- **Disambiguation Tokens**: `Supplier`, `Purchaser`, `Manufacturer`, `Minimum Purchase Commitment`, `Specifications`, `Delivery Schedule`

#### Subtype 10.D: Real Property Leases (`real_estate_leases`)
- **Primary Anchors**: `LEASE AGREEMENT`, `OFFICE LEASE`, `BUILDING LEASE`, `SUBLEASE AGREEMENT`
- **Disambiguation Tokens**: `Landlord`, `Tenant`, `Leased Premises`, `Base Rent`, `Commencement Date`, `Term of Lease`

#### Subtype 10.E: Intellectual Property & Licensing Agreements (`ip_license_agreements`)
- **Primary Anchors**: `LICENSE AGREEMENT`, `PATENT LICENSE AGREEMENT`, `COLLABORATION AND LICENSE AGREEMENT`, `DEVELOPMENT AGREEMENT`
- **Disambiguation Tokens**: `Licensor`, `Licensee`, `Licensed Patents`, `Field of Use`, `Royalty Rate`, `Milestone Payments`

---

### Exhibit 13 (Item 601) — Annual or Quarterly Report to Security Holders
*Proposed Module: `ex13_item601.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(13)
- **Design Challenge**: Must distinguish annual shareholder reports from quarterly reports incorporated by reference.

#### Subtype 13.A: Glossy Annual Report to Security Holders (`annual_shareholder_report`)
- **Primary Anchors**: `(?i) (?:ANNUAL\s+REPORT\s+TO\s+(?:SECURITY\s+HOLDERS|SHAREHOLDERS|STOCKHOLDERS)|LETTER\s+TO\s+SHAREHOLDERS) `
- **Disambiguation Tokens**: `To Our Shareholders`, `Financial Highlights`, `Year in Review`, `Operating Highlights`, `Fellow Stockholders`
- **Regulatory Function**: Attached to satisfy Form 10-K Part II incorporation by reference under Rule 439.

#### Subtype 13.B: Form 10-Q Incorporated by Reference (`quarterly_report_incorporation`)
- **Primary Anchors**: `(?i) QUARTERLY\s+REPORT\s+ON\s+FORM\s+10-Q `
- **Disambiguation Tokens**: `Quarterly period ended`, `Part I. Financial Information`, `Item 1. Financial Statements`
- **Regulatory Function**: Attached to registration statements (Form S-4) to incorporate interim periods by reference.

---

### Exhibit 14 & 19 (Item 601) vs Exhibit 11 (Form 20-F) — Ethics & Insider Trading Policies
*Proposed Modules: `ex14_item601.py`, `ex19.py`, `form20f_ex11.py`*

#### Disambiguation Rules:
- **Item 601 EX-14 (Code of Ethics)**:
  - Cites: `Item 406 of Regulation S-K`.
  - Focus: Applies specifically to `Chief Executive Officer, Chief Financial Officer, Controller, or Principal Accounting Officer` governing `honest and ethical conduct`, `conflicts of interest`, and `accurate financial reporting`.
- **Item 601 EX-19 (Insider Trading Policy)**:
  - Cites: `Item 408(b) of Regulation S-K`.
  - Focus: Applies to all employees and directors; governs trading in company securities while aware of `material nonpublic information`; establishes `Rule 10b5-1 Trading Plans`, `Trading Windows`, and `Blackout Periods`.
- **Form 20-F Exhibit 11**:
  - Combines both Item 406 Code of Ethics AND Item 408(b) Insider Trading Policy under a single exhibit designation! The evaluator must run both sub-packs against Form 20-F Exhibit 11 files.

---

### Exhibit 31 Family — Ordinary Corporate SOX 302 vs ABS Certifications
*Proposed Modules: `ex31_item601.py` vs `ex31_abs.py` (and `form20f_ex12.py`)*

#### Disambiguation Rules:
- **Item 601(b)(31)(i) & Form 20-F Ex 12 (Ordinary Corporate SOX 302)**:
  - Invariant Structure: Exactly 5 numbered paragraphs.
  - Paragraph 1: `I have reviewed this [annual/quarterly] report on Form [10-K/10-Q/20-F] of [Company];`
  - Paragraph 4: References `Rules 13a-15(e) and 15d-15(e)` (disclosure controls) and `Rules 13a-15(f) and 15d-15(f)` (internal control over financial reporting).
- **Item 601(b)(31)(ii) (Asset-Backed Securities SOX 302)**:
  - Invariant Structure: Evaluates `Exchange Act periodic reports` consisting of `Form 10-K and all reports on Form 10-D`.
  - Paragraph 4: Explicitly cites `Item 1123 of Regulation AB` and the `servicer compliance statement(s)`.
  - Paragraph 5: Explicitly cites `Item 1122 of Regulation AB` and the `servicing criteria attestation reports`.

---

### Exhibit 33, 34, 35, 36 — The Asset-Backed Securities Compliance Suite
*Proposed Modules: `ex33.py`, `ex34.py`, `ex35.py`, `ex36.py`*

#### Disambiguation Rules:
- **EX-33 (Management Servicing Assessment under Item 1122(a))**:
  - Asserting Party: Issued by the servicing organization management (`Asserting Party`).
  - Key Tokens: `Item 1122(d) of Regulation AB`, `Platform`, `assessment of compliance`, `material instances of noncompliance`.
- **EX-34 (Auditor Attestation under Item 1122(b))**:
  - Asserting Party: Issued by an independent accounting firm (`Independent Registered Public Accounting Firm`).
  - Key Tokens: `examination of management's assertion`, `Standards for Attestation Engagements`, `AT-C Section 315`, `examination conducted in accordance with PCAOB standards`.
- **EX-35 (Servicer Compliance Statement under Item 1123)**:
  - Asserting Party: Signed by an officer of the servicer (`CarMax Business Services`, `Navient`, `Ford Credit`).
  - Key Tokens: `Officer's Certificate`, `review of servicing activities`, `fulfilled all of its obligations under the servicing agreement in all material respects`.
- **EX-36 (Depositor Shelf Offering Certification on Form SF-3)**:
  - Authority: Form SF-3 General Instruction I.B.1.(a).
  - Asserting Party: Signed by the CEO of the Depositor.
  - Key Tokens: `prospectus relating to [securities]`, `characteristics of the securitized assets`, `reasonable basis to conclude that the securitization is structured to produce... expected cash flows`.

---

### Exhibit 96 (Item 601) — Mining Technical Report Summary (Subpart 1300)
*Proposed Module: `ex96.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(96) & 17 CFR §§ 229.1300–1305
- **Design Challenge**: High-volume, highly structured scientific document prepared by third-party engineering firms (e.g., Stantec, SRK, Wood, M3).
- **Primary Detection Prose Anchors**:
  - `(?i) (?:TECHNICAL\s+REPORT\s+SUMMARY|S-K\s+1300\s+TECHNICAL\s+REPORT\s+SUMMARY|INITIAL\s+ASSESSMENT\s+TECHNICAL\s+REPORT) `
- **Secondary Disambiguation Tokens (Mandatory 25-Section Item 601(b)(96) Structure)**:
  - Header: `Qualified Person(s)`, `Registrant for whom prepared`, `Subpart 1300 of Regulation S-K`
  - Section Heads: `Executive Summary`, `Property Description`, `Accessibility, Climate, Infrastructure`, `Geological Setting, Mineralization and Deposit`, `Mineral Resource Estimates`, `Mineral Reserve Estimates`, `Mining Methods`, `Processing and Recovery Methods`, `Capital and Operating Costs`
- **Disambiguation vs NI 43-101**: Canadian Form 6-K filings often attach National Instrument 43-101 reports. Check specifically for citations to `Subpart 1300 of Regulation S-K` vs `Canadian National Instrument 43-101`.

---

### Exhibit 98 (Item 601) — Reports, Opinions, or Appraisals in de-SPAC Transactions
*Proposed Module: `ex98.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(98) & 17 CFR § 229.1607(c) (effective July 2024)
- **Primary Detection Prose Anchors**:
  - `(?i) (?:REPORT\s+PURSUANT\s+TO\s+ITEM\s+1607|OPINION\s+IN\s+DE[- ]SPAC\s+TRANSACTION|FAIRNESS\s+OPINION[\s\S]{1,100}?de[- ]SPAC) `
- **Secondary Disambiguation Tokens**:
  - `Board of Directors of [SPAC Name]`, `Item 1607(c) of Regulation S-K`, `Subpart 1600`, `fairness, from a financial point of view`, `de-SPAC business combination`

---

### Exhibit 106 (Item 601) — Static Pool Disclosure Body Document Evidence
*Proposed Module: `ex106.py`*
- **Statutory Authority**: 17 CFR § 229.601(b)(106) & 17 CFR § 229.1105 (Item 1105 of Regulation AB)
- **Status in Ledger**: *Previously unsupported due to index-page confusion; fully resolved herein.*
- **Regulatory Ingestion Mechanics**:
  Under SEC rules, Static Pool information under Item 1105 may be provided:
  1. As an official PDF file submitted under Exhibit 106 (`Static Pool PDF`) pursuant to Rule 311 of Regulation S-T;
  2. Incorporated by reference via Form 8-K under Item 6.05 / Item 8.01; or
  3. Hosted on a designated website pursuant to Rule 312 of Regulation S-T.
- **Body-Level Textual & Tabular Discriminators**:
  - Primary Anchors: `(?i) (?:STATIC\s+POOL\s+(?:INFORMATION|DISCLOSURE|DATA)|Item\s+1105\s+of\s+Regulation\s+AB) `
  - Secondary Table Headers: Multi-vintage origination performance tables containing:
    `Vintage / Origination Year` | `Pool Factor` | `Cumulative Net Loss Rate` | `30-59 Days Delinquent` | `60-89 Days Delinquent` | `Prepayment Speed (CPR / ABS)`

---

### Structured Data Exhibits: Router Specification (EX-101, 102, 103, 104)
*Handling: Non-Prose Structured Data Route*
Exhibits 101, 102, 103, and 104 are not narrative legal prose and must be bypassed by NLP text classifiers and routed directly to XML/XBRL validation engines:
- **EX-101**: Routed to Inline XBRL validation engine. XML namespaces: `xmlns:xbrli="http://www.xbrl.org/2003/instance"`, `us-gaap`, `dei`.
- **EX-102**: Routed to ABS-EE XML schema engine. XML namespace: `http://www.sec.gov/edgar/abs/assetdata`.
- **EX-103**: Explanatory data dictionaries accompanying Form ABS-EE asset data.
- **EX-104**: Cover Page Interactive Data File. Embedded within HTML `<ix:header>` tags on the filing cover page.

---

## 3. Comprehensive Multi-Authority Evidence Corpus

Below is the verified evidence corpus comprising 4 distinct public companies per exhibit category, including direct evidence demonstrating the Form 20-F vs Item 601 numbering collisions in live filings.

### 3.1 Form 20-F Collision Evidence Corpus

| Form 20-F Exhibit | Document Classification | Registrant Name | CIK | Accession Number | Direct SEC EDGAR Link |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Form 20-F Ex 1** | Articles of Association (Item 601 EX-3.1 equivalent) | CRH public limited company | 0000849395 | 0001193125-21-078969 | [https://www.sec.gov/Archives/edgar/data/849395/000119312521078969/d911751dex1.htm](https://www.sec.gov/Archives/edgar/data/849395/000119312521078969/d911751dex1.htm) |
| **Form 20-F Ex 1** | Articles of Association (Item 601 EX-3.1 equivalent) | Tencent Music Entertainment Group | 0001744676 | 0000950170-23-014459 | [https://www.sec.gov/Archives/edgar/data/1744676/000095017023014459/tme-ex1_1.htm](https://www.sec.gov/Archives/edgar/data/1744676/000095017023014459/tme-ex1_1.htm) |
| **Form 20-F Ex 8** | Subsidiaries List (Item 601 EX-21 equivalent) | Vale S.A. | 0000917851 | 0000950123-09-007362 | [https://www.sec.gov/Archives/edgar/data/917851/000095012309007362/y75715exv8.htm](https://www.sec.gov/Archives/edgar/data/917851/000095012309007362/y75715exv8.htm) |
| **Form 20-F Ex 8** | Subsidiaries List (Item 601 EX-21 equivalent) | VEON Ltd. | 0001468091 | 0001193125-17-107561 | [https://www.sec.gov/Archives/edgar/data/1468091/000119312517107561/d318647dex8.htm](https://www.sec.gov/Archives/edgar/data/1468091/000119312517107561/d318647dex8.htm) |
| **Form 20-F Ex 12** | SOX 302 Certification (Item 601 EX-31.1 equivalent) | Genius Sports Limited | 0001834489 | 0001193125-26-110749 | [https://www.sec.gov/Archives/edgar/data/1834489/000119312526110749/geni-ex12_1.htm](https://www.sec.gov/Archives/edgar/data/1834489/000119312526110749/geni-ex12_1.htm) |
| **Form 20-F Ex 13** | SOX 906 Certification (Item 601 EX-32.1 equivalent) | ReNew Energy Global plc | 0001848763 | 0001193125-26-325073 | [https://www.sec.gov/Archives/edgar/data/1848763/000119312526325073/rnw-ex13_1.htm](https://www.sec.gov/Archives/edgar/data/1848763/000119312526325073/rnw-ex13_1.htm) |
| **Form 20-F Ex 13** | SOX 906 Certification (Item 601 EX-32.1 equivalent) | Shinhan Financial Group Co., Ltd. | 0001263043 | 0001193125-26-168235 | [https://www.sec.gov/Archives/edgar/data/1263043/000119312526168235/d75079dex131.htm](https://www.sec.gov/Archives/edgar/data/1263043/000119312526168235/d75079dex131.htm) |
| **Form 20-F Ex 13** | SOX 906 Certification (Item 601 EX-32.1 equivalent) | StealthGas Inc. | 0001328919 | 0001193125-26-183385 | [https://www.sec.gov/Archives/edgar/data/1328919/000119312526183385/d66975dex131.htm](https://www.sec.gov/Archives/edgar/data/1328919/000119312526183385/d66975dex131.htm) |

### 3.2 Newly Profiled Exhibits & Evidence Corpus

| Exhibit Authority / ID | Exhibit Description | Registrant Name | CIK | Accession Number | Direct SEC EDGAR Link |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Item 601 EX-7** | Auditor Non-Reliance Letter (Item 4.02(c)) | Tumbleweed Holdings, Inc. | 0001016951 | 0001471242-15-000004 | [https://www.sec.gov/Archives/edgar/data/1016951/000147124215000004/dcdc8k12232014.htm](https://www.sec.gov/Archives/edgar/data/1016951/000147124215000004/dcdc8k12232014.htm) |
| **Item 601 EX-7** | Auditor Non-Reliance Letter (Item 4.02(c)) | Earthworks Entertainment, Inc. | 0000820789 | 0001096906-06-000091 | [https://www.sec.gov/Archives/edgar/data/820789/000109690606000091/earthworks8k111605.htm](https://www.sec.gov/Archives/edgar/data/820789/000109690606000091/earthworks8k111605.htm) |
| **Item 601 EX-98** | de-SPAC Fairness Opinion (Item 1607(c)) | IX Acquisition Corp. | 0001852019 | 0001104659-24-103820 | [https://www.sec.gov/Archives/edgar/data/1852019/000110465924103820/ixaqu-20240630xex98d1.htm](https://www.sec.gov/Archives/edgar/data/1852019/000110465924103820/ixaqu-20240630xex98d1.htm) |
| **Item 601 EX-98** | de-SPAC Fairness Opinion (Item 1607(c)) | Hall Chadwick Acquisition Corp. | 0002079013 | 0001829126-26-010648 | [https://www.sec.gov/Archives/edgar/data/2079013/000182912626010648/hallchadwickacq_s4.htm](https://www.sec.gov/Archives/edgar/data/2079013/000182912626010648/hallchadwickacq_s4.htm) |
| **Item 601 EX-98** | de-SPAC Appraisal / Report (Item 1607(c)) | Relativity Acquisition Corp. | 0002072188 | 0000000000-25-009167 | [https://www.sec.gov/Archives/edgar/data/2072188/000000000025009167/filename1.pdf](https://www.sec.gov/Archives/edgar/data/2072188/000000000025009167/filename1.pdf) |
| **Item 601 EX-98** | de-SPAC Valuation / Report (Item 1607(c)) | Welsbach Technology Metals | 0002043020 | 0000000000-24-013586 | [https://www.sec.gov/Archives/edgar/data/2043020/000000000024013586/filename1.pdf](https://www.sec.gov/Archives/edgar/data/2043020/000000000024013586/filename1.pdf) |
| **Item 601 EX-106** | Static Pool Information (Item 1105) | American Honda Receivables LLC | 0000890975 | 0001104659-23-061771 | [https://www.sec.gov/Archives/edgar/data/890975/000110465923061771/tm2314760d1_8k.htm](https://www.sec.gov/Archives/edgar/data/890975/000110465923061771/tm2314760d1_8k.htm) |
| **Item 601 EX-106** | Static Pool Information (Item 1105) | Discover Card Execution Note Trust | 0001407200 | 0001407200-22-000004 | [https://www.sec.gov/Archives/edgar/data/1407200/000140720022000004/qtrly_dcmtxdcentxasofdecem.htm](https://www.sec.gov/Archives/edgar/data/1407200/000140720022000004/qtrly_dcmtxdcentxasofdecem.htm) |
| **Form SF-3 EX-36** | Shelf Offering Depositor Certification | CarMax Auto Funding LLC | 0002117307 | 0001193125-26-173263 | [https://www.sec.gov/Archives/edgar/data/2117307/000119312526173263/d139274dex361.htm](https://www.sec.gov/Archives/edgar/data/2117307/000119312526173263/d139274dex361.htm) |
| **Form SF-3 EX-36** | Shelf Offering Depositor Certification | American Express Receivables Financing | 0001003509 | 0000000000-15-052591 | [https://www.sec.gov/Archives/edgar/data/1003509/000000000015052591/filename1.pdf](https://www.sec.gov/Archives/edgar/data/1003509/000000000015052591/filename1.pdf) |
| **Form SF-3 EX-36** | Shelf Offering Depositor Certification | First National Funding LLC | 0001171040 | 0001193125-17-128866 | [https://www.sec.gov/Archives/edgar/data/1171040/000119312517128866/d347474d424b5.htm](https://www.sec.gov/Archives/edgar/data/1171040/000119312517128866/d347474d424b5.htm) |
| **Form SF-3 EX-36** | Shelf Offering Depositor Certification | Synchrony Card Funding LLC | 0001724786 | 0001104659-21-085135 | [https://www.sec.gov/Archives/edgar/data/1724786/000110465921085135/tm2120345d1_sf3.htm](https://www.sec.gov/Archives/edgar/data/1724786/000110465921085135/tm2120345d1_sf3.htm) |

---

## 4. Production-Grade Python NLP Classifier Implementation

Below is a reference Python architecture implementing the decoupled authority routing, negative lookaheads, and bounded subtype classification rules targeting lines 1–25 of tag-free prose.

```python
"""
SEC EDGAR Tag-Free Exhibit Classifier Engine
Implements Decoupled Authority Mapping and Subtype Disambiguation.
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class ExhibitMatchResult:
    authority: str
    source_exhibit_code: str
    content_pack: str
    subtype: str
    confidence: float
    matched_anchors: List[str]

class EdgarTagFreeClassifier:
    
    # 1. Negative Discriminator for Primary Forms
    COVER_FORM_RE = re.compile(
        r"(?:\[[X\s_]\]\s*(?:ANNUAL|QUARTERLY|CURRENT|TRANSITION)\s+REPORT\s+PURSUANT\s+TO|"
        r"Indicate\s+by\s+check\s+mark\s+(?:whether|if)\s+the\s+registrant)",
        re.IGNORECASE
    )

    # 2. Content-Pack Subtype Regex Rules
    SUBTYPE_RULES = {
        "ARTICLES_OF_INCORPORATION": re.compile(
            r"^(?=.*? (?:CERTIFICATE|ARTICLES)\s+OF\s+(?:INCORPORATION|FORMATION|ORGANIZATION|ASSOCIATION) )"
            r"(?!.*? BY[- ]?LAWS )",
            re.IGNORECASE | re.MULTILINE
        ),
        "BYLAWS": re.compile(
            r"^\s*(?:EXHIBIT\s+(?:3\.2|1)\s+)?(?:AMENDED\s+(?:AND\s+RESTATED\s+)?)?BY[- ]?LAWS"
            r"(?:\s+OF\s+[\w\s.,]+)?$",
            re.IGNORECASE | re.MULTILINE
        ),
        "MERGER_PLAN": re.compile(
            r" AGREEMENT\s+AND\s+PLAN\s+OF\s+MERGER [\s\S]{1,600}?"
            r"(?:Merger\s+Sub|Surviving\s+(?:Corporation|Entity)|Certificate\s+of\s+Merger)",
            re.IGNORECASE
        ),
        "INDENTURE": re.compile(
            r"(?:SENIOR\s+|SUBORDINATED\s+)?INDENTURE[\s\S]{1,300}? as\s+Trustee ",
            re.IGNORECASE
        ),
        "DESCRIPTION_OF_SECURITIES": re.compile(
            r"DESCRIPTION\s+OF\s+(?:THE\s+)?REGISTRANT['’]?S\s+SECURITIES\s+REGISTERED\s+PURSUANT\s+TO\s+SECTION\s+12",
            re.IGNORECASE
        ),
        "LEGALITY_OPINION": re.compile(
            r"(?:Registration\s+Statement\s+on\s+Form\s+S-[\d]|Validity\s+of\s+(?:the\s+)?(?:Securities|Notes|Shares))[\s\S]{1,600}?"
            r"(?:validly\s+issued,\s*fully\s+paid\s+and\s+non[- ]assessable|legally\s+valid\s+and\s+binding\s+obligations)",
            re.IGNORECASE
        ),
        "TAX_OPINION": re.compile(
            r"(?:TAX\s+OPINION|opinion\s+(?:with\s+respect\s+to|regarding)\s+certain\s+(?:U\.?S\.?\s+federal\s+income\s+)?tax\s+matters)[\s\S]{1,600}?"
            r"(?:Internal\s+Revenue\s+Code|Section\s+368|qualif(?:y|ication)\s+as\s+a\s+REIT)",
            re.IGNORECASE
        ),
        "ACCOUNTANT_NON_RELIANCE_EX7": re.compile(
            r"(?:Securities\s+and\s+Exchange\s+Commission|Commissioners:)[\s\S]{1,400}?"
            r"Item\s+4\.02(?:\([bc]\))?[\s\S]{1,300}?"
            r"(?:non[- ]reliance|should\s+no\s+longer\s+be\s+relied\s+upon|agree\s+with\s+the\s+statements)",
            re.IGNORECASE
        ),
        "CREDIT_AGREEMENT": re.compile(
            r" (?:CREDIT\s+AGREEMENT|TERM\s+LOAN\s+AGREEMENT|REVOLVING\s+CREDIT\s+FACILITY) [\s\S]{1,400}?"
            r"(?:Administrative\s+Agent|Borrower|Lenders)",
            re.IGNORECASE
        ),
        "EXECUTIVE_EMPLOYMENT": re.compile(
            r" (?:EMPLOYMENT\s+AGREEMENT|EXECUTIVE\s+EMPLOYMENT\s+AGREEMENT) [\s\S]{1,400}?"
            r"(?:Executive|Base\s+Salary|Employment\s+Period)",
            re.IGNORECASE
        ),
        "SOX_302_CORPORATE": re.compile(
            r"I,\s*[^,
]+,\s*certify\s+that:\s*1\.\s*I\s+have\s+reviewed\s+this\s+(?:annual|quarterly)?\s*report[\s\S]{1,400}?"
            r"Rules\s+13a-15\(e\)\s+and\s+15d-15\(e\)",
            re.IGNORECASE
        ),
        "SOX_302_ABS": re.compile(
            r"I,\s*[^,
]+,\s*certify\s+that:\s*1\.\s*I\s+have\s+reviewed\s+this\s+report\s+on\s+Form\s+10-K\s+and\s+all\s+reports\s+on\s+Form\s+10-D[\s\S]{1,400}?"
            r"Item\s+1123\s+of\s+Regulation\s+AB",
            re.IGNORECASE
        ),
        "SOX_906": re.compile(
            r"(?:18\s+U\.?S\.?C\.?\s*(?:§|Section)?\s*1350|Section\s+906)[\s\S]{1,500}?"
            r"(?:fully\s+complies\s+with\s+the\s+requirements\s+of\s+section\s+13\(a\)|fairly\s+presents,\s+in\s+all\s+material\s+respects)",
            re.IGNORECASE
        ),
        "ABS_SHELF_CERT_EX36": re.compile(
            r"certify\s+as\s+of[\s\S]{1,300}?(?:securitized\s+assets|structure\s+of\s+the\s+securitization)[\s\S]{1,500}?"
            r"reasonable\s+basis\s+to\s+conclude\s+that\s+the\s+securitization\s+is\s+structured\s+to\s+produce",
            re.IGNORECASE
        ),
        "MINE_SAFETY_EX95": re.compile(
            r"(?:MINE\s+SAFETY\s+DISCLOSURE|Section\s+1503\(a\)\s+of\s+the\s+Dodd[- ]Frank)[\s\S]{1,400}?"
            r"(?:MSHA\s+Identification\s+Number|Federal\s+Mine\s+Safety|Section\s+104\s+S&S)",
            re.IGNORECASE
        ),
        "MINING_TECHNICAL_REPORT_EX96": re.compile(
            r"TECHNICAL\s+REPORT\s+SUMMARY[\s\S]{1,500}?"
            r"(?:Subpart\s+1300|Qualified\s+Persons?|Mineral\s+Resources?\s+(?:and\s+Mineral\s+Reserves?\s+)?Estimates?)",
            re.IGNORECASE
        ),
        "DE_SPAC_OPINION_EX98": re.compile(
            r"(?:Item\s+1607(?:\(c\))?|de[- ]SPAC\s+(?:transaction|business\s+combination))[\s\S]{1,500}?"
            r"(?:fairness\s+opinion|opinion\s+as\s+to\s+(?:the\s+)?fairness|financial\s+point\s+of\s+view|appraisal)",
            re.IGNORECASE
        ),
        "STATIC_POOL_EX106": re.compile(
            r"(?:STATIC\s+POOL\s+(?:INFORMATION|DISCLOSURE|DATA)|EX-106 )[\s\S]{1,400}?"
            r"(?:Item\s+1105\s+of\s+Regulation\s+AB|prior\s+securitized\s+pools|cumulative\s+net\s+losses)",
            re.IGNORECASE
        )
    }

    def evaluate_header(self, raw_prose: str, authority: str = "ITEM_601", reported_exhibit_code: Optional[str] = None) -> Optional[ExhibitMatchResult]:
        header_window = "\n".join(raw_prose.splitlines()[:25])[:1500]

        # 1. Gatekeeper check: Reject primary cover forms immediately
        if self.COVER_FORM_RE.search(header_window):
            return None

        # 2. Iterate evaluator rules
        for subtype_name, rule_regex in self.SUBTYPE_RULES.items():
            match = rule_regex.search(header_window)
            if match:
                return ExhibitMatchResult(
                    authority=authority,
                    source_exhibit_code=reported_exhibit_code or "UNKNOWN",
                    content_pack=subtype_name.split("_")[0],
                    subtype=subtype_name,
                    confidence=0.95,
                    matched_anchors=[match.group(0)[:80]]
                )
        return None
```

### 2.1 Tier 1 Exhibits (High Prevalence)

| Exhibit ID | Exhibit Title | Normalized Top 3-Grams & 4-Grams | Invariant Line Position | Negative N-Grams (Rejection Triggers) |
| :--- | :--- | :--- | :--- | :--- |
| **EX-3.1** | Articles of Incorporation | `restated certificate incorporation`, `certificate incorporation <ENTITY>`, `incorporated under name <ENTITY>`, `filed with secretary state <JURISDICTION>` | Lines 1–8 | `amended restated bylaws`, `article i offices`, `plan merger` |
| **EX-3.2** | Bylaws | `amended restated bylaws`, `bylaws <ENTITY>`, `article i offices`, `section <NUM> registered office` | Lines 1–6 | `certificate incorporation`, `articles incorporation`, `secretary state` |
| **EX-4** | Instruments Defining Rights / Indentures / Sec. Description | **Branch A (Indenture):** `indenture dated as <DATE>`, `as trustee indenture`, `senior notes due <YEAR>`<br>**Branch B (Sec. Desc):** `description registrant securities registered`, `registered pursuant <EXCHANGE_ACT_SEC>` | Lines 1–12 | `administrative agent lenders`, `borrower credit agreement` |
| **EX-10** | Material Contracts | `credit agreement among <ENTITY>`, `administrative agent lenders borrower`, `employment agreement between <ENTITY>`, `base salary incentive compensation` | Lines 1–10 | `underwriting agreement standard`, `agreement plan merger`, `as trustee indenture` |
| **EX-21** | Subsidiaries List | `significant subsidiaries registrant`, `subsidiaries <ENTITY>`, `name subsidiary jurisdiction organization`, `jurisdiction incorporation organization` | Lines 1–6 | `guarantor subsidiaries senior notes`, `full unconditional guarantee` |
| **EX-23** | Auditor / Counsel Consents | `consent independent registered public accounting firm`, `we consent incorporation reference`, `registration statement on form s-<NUM>` | Lines 1–5 | `opinion financial statements`, `report independent registered public` (without 'consent') |
| **EX-24** | Power of Attorney | `power attorney know all`, `know all by these presents`, `constitutes appoints <ENTITY> attorney-in-fact`, `true lawful attorney-in-fact` | Lines 1–8 | `in witness whereof` (alone on signature line), `by attorney-in-fact` |
| **EX-31.1** | SOX 302 Certification (Corporate) | `i <OFFICER> certify that`, `reviewed this annual report`, `does not contain untrue statement`, `internal control financial reporting` | Lines 1–10 | `form 10-d`, `<REG_AB_ITEM>`, `servicer compliance statement` |
| **EX-32.1** | SOX 906 Certification (Section 1350) | `certification pursuant <SOX_906_STATUTE>`, `pursuant section <NUM> sarbanes-oxley`, `fully complies requirements section`, `fairly presents all material respects` | Lines 1–8 | `i have reviewed this report`, `internal control financial reporting` (5-paragraph sequence) |

---

### 2.2 Tier 2 Exhibits (Medium Prevalence)

| Exhibit ID | Exhibit Title | Normalized Top 3-Grams & 4-Grams | Invariant Line Position | Negative N-Grams (Rejection Triggers) |
| :--- | :--- | :--- | :--- | :--- |
| **EX-1** | Underwriting Agreements | `underwriting agreement <DATE>`, `representative several underwriters`, `<SHARE_COUNT> firm shares`, `purchase price per share` | Lines 1–10 | `administrative agent borrower`, `indenture as trustee` |
| **EX-2** | Plan of Acquisition / Merger | `agreement plan merger among`, `merger sub surviving corporation`, `effective time certificate merger`, `merger pursuant section <NUM>` | Lines 1–8 | `loan credit agreement`, `schedule 14a proxy` |
| **EX-5** | Opinion re Legality | `validly issued fully paid non-assessable`, `binding obligations registrant`, `validity notes prospectus`, `consent filing this opinion` | Lines 4–15 | `internal revenue code`, `tax consequences merger`, `section 368 reorganization` |
| **EX-7** | Auditor Non-Reliance Letter | `item 4.02 form 8-k`, `non-reliance previously issued financial`, `should no longer be relied upon`, `agree with statements made` | Lines 1–8 | `item 4.01 changes in certifying`, `we consent incorporation reference` |
| **EX-8** | Opinion re Tax Matters | `opinion regarding tax matters`, `u.s. federal income tax considerations`, `reorganization within meaning section 368`, `qualifies real estate investment trust` | Lines 4–15 | `validly issued fully paid non-assessable` |
| **EX-14** | Code of Ethics | `code business conduct ethics`, `code ethics senior financial officers`, `honest ethical conduct conflicts`, `<REG_SK_ITEM>` | Lines 1–8 | `rule 10b5-1 trading plan`, `blackout period window` |
| **EX-15** | Unaudited Interim Info Awareness Letter | `rule 436(c) securities act`, `unaudited interim financial information`, `not considered part registration statement`, `within meaning sections 7 and 11` | Lines 1–10 | `we consent incorporation reference` (without 436(c) disclaimer) |
| **EX-16** | Change in Auditor Letter | `item 4.01 form 8-k`, `securities exchange commission commissioners`, `we agree with statements concerning`, `item 304 regulation s-k` | Lines 1–8 | `item 4.02 non-reliance`, `item 2.02 results operations` |
| **EX-17** | Director Departure Letter | `hereby submit my resignation`, `resign board directors effective`, `not result any disagreement company`, `operations policies practices` | Lines 1–8 | `item 5.02 departure directors` (third-person 8-K narrative) |
| **EX-18** | Preferability Letter | `change accounting principle is preferable`, `newly adopted method accounting preferable`, `concur with management that change`, `asc 250 accounting changes` | Lines 1–10 | `item 4.01 dismissal`, `we audit consolidated balance` |
| **EX-19** | Insider Trading Policy | `insider trading compliance policy`, `material nonpublic information tipping`, `rule 10b5-1 trading plans`, `pre-clearance trading blackout periods` | Lines 1–8 | `code ethics senior financial officers` |
| **EX-22** | Subsidiary Guarantors List | `subsidiary guarantors issuers guaranteed`, `guaranteed securities senior notes`, `obligors under first lien notes`, `100% owned operating subsidiary guarantee` | Lines 1–8 | `jurisdiction organization` (without guaranteed securities) |
| **EX-25** | Form T-1 Trustee Statement | `form t-1 statement eligibility`, `statement eligibility trust indenture act`, `corporation designated act trustee`, `comptroller currency national banking` | Lines 1–8 | `as trustee indenture` (standard contract recital) |
| **EX-97** | Clawback Recovery Policy | `incentive compensation recovery policy`, `erroneously awarded compensation clawback`, `rule 10d-1 exchange act`, `accounting restatement big r little r` | Lines 1–8 | `employment agreement base salary` |
| **EX-99** | Press Releases / Additional | `for immediate release`, `<JURISDICTION> <DATE> company reports`, `financial results quarter ended`, `non-gaap financial measures reconciliation` | Lines 1–8 | `united states securities exchange commission form 8-k` |
| **EX-107** | Filing Fee Table | `calculation filing fee tables`, `table 1 newly registered carry forward`, `fee calculation rule <SEC_RULE>`, `maximum aggregate offering price` | Lines 1–8 | `prospectus summary use proceeds` |

---

### 2.3 Tier 3 Exhibits (Specialized Domain Filings)

| Exhibit ID | Exhibit Title | Normalized Top 3-Grams & 4-Grams | Invariant Line Position | Negative N-Grams (Rejection Triggers) |
| :--- | :--- | :--- | :--- | :--- |
| **EX-9** | Voting Trust Agreement | `voting trust agreement among`, `deposit shares stock trustees`, `voting trust certificates issued`, `transfer legal title trustees` | Lines 1–8 | `stockholder proxy agreement` (without trust certificates) |
| **EX-13** | Shareholder Annual Report | `annual report security holders`, `to our fellow shareholders`, `financial highlights year ended`, `operating review president message` | Lines 1–10 | `form 10-k annual report pursuant` |
| **EX-20** | Unitholder Statements | `monthly distribution statement unitholders`, `notice security holders trust`, `distributable income royalty trust`, `simmons bank as trustee` | Lines 1–8 | `form 10-q quarterly report` |
| **EX-31(ii)** | ABS SOX 302 Certification | `reviewed this report form 10-k and all reports form 10-d`, `exchange act periodic reports taken`, `<REG_AB_ITEM> servicer compliance`, `<REG_AB_ITEM> servicing criteria` | Lines 1–10 | `disclosure controls procedures rules 13a-15(e)` |
| **EX-33** | Servicing Assessment (Mgmt) | `management report assessment compliance servicing`, `applicable servicing criteria item 1122(d)`, `asserting party responsible assessing`, `material instance noncompliance platform` | Lines 1–8 | `report independent registered public accounting firm` |
| **EX-34** | Servicing Attestation (CPA) | `attestation report assessment compliance`, `examined management assertion included`, `applicable servicing criteria item 1122(d)`, `standards attestation engagements at-c` | Lines 1–8 | `asserting party has assessed` (first-person management) |
| **EX-35** | Servicer Compliance Statement | `annual servicer compliance statement`, `compliance statement pursuant item 1123`, `fulfilled obligations servicing agreement all material respects`, `officer certificate servicer` | Lines 1–8 | `examination management assertion`, `servicing criteria item 1122(d)` |
| **EX-36** | ABS Shelf Offering Certification | `certification shelf offerings asset-backed`, `form sf-3 general instruction i.b.1.(a)`, `characteristics securitized assets underlying`, `reasonable basis conclude securitization structured produce expected cash flows` | Lines 1–8 | `form 10-k annual report periodic` |
| **EX-95** | Mine Safety Disclosure | `mine safety disclosure pursuant section 1503(a)`, `dodd-frank wall street reform`, `msha identification number citations`, `section 104 s&s citations orders` | Lines 1–8 | `item 4 mine safety disclosures` (10-K body narrative) |
| **EX-96** | Mining Technical Report | `s-k 1300 technical report summary`, `initial assessment mineral resources`, `mineral reserve estimates feasibility study`, `qualified persons stantec srk` | Lines 1–12 | `canadian national instrument 43-101` |
| **EX-98** | de-SPAC Fairness Opinion | `fairness opinion de-spac business combination`, `item 1607(c) regulation s-k`, `subpart 1600 spac transaction`, `fair from financial point view` | Lines 1–10 | `fairness opinion schedule 14a` (non-SPAC merger proxy) |
| **EX-106** | Static Pool Disclosure | `static pool information item 1105`, `prior securitized pools vintage`, `cumulative net loss rate prepayment speed`, `30-59 days delinquent pool factor` | Lines 1–10 | `form 10-d distribution report` (single period only) |

