# SEC EDGAR Collision Analysis: Exhibits vs. Actual Primary SEC Forms (10-K, 20-F, 8-K, etc.)
**Taxonomy Collisions, Lexical Self-References, and Disambiguation Architecture for NLP Pipelines**

---

## 1. Executive Summary: The Three Dimensions of Exhibit–Form Collisions

In automated SEC EDGAR parsing, natural language processing (NLP), and document classification pipelines, exhibits do not exist in isolation. They frequently collide with primary SEC forms (e.g., Form 10-K, 20-F, 8-K, 10-Q, S-1, DEF 14A, Forms 3/4/5) across three distinct technical dimensions:

1. **Dimension 1: Lexical Self-Reference Collisions** (Exhibits that explicitly name the primary form in lines 1–10).
2. **Dimension 2: Identity & Structural Subsumption Collisions** (Exhibits that *are* actual SEC forms or wrap full standalone forms).
3. **Dimension 3: Namespace / Numbering Collisions** (Exhibit codes that match or overlap with SEC form names).

Without explicit disambiguation rules, naive keyword extractors, bag-of-words classifiers, and n-gram models regularly misclassify exhibit attachments as primary filings or vice versa.

---

## 2. Dimension 1: Lexical Self-Reference Collisions

Many Item 601 exhibits are legally required to refer to the host registration statement or periodic report within their opening recitals. If an NLP model relies on naive form-name matching (`"Form 10-K"`, `"Form 20-F"`, `"Form 8-K"`), these exhibits produce immediate false positives.

### Lexical Self-Reference Collision Matrix

| Exhibit Code & Title | Host Form Reference in Header (Lines 1–10) | Exact Raw Header Text Snippet | Why Naive NLP Fails | Disambiguation Rule & Distinguishing Feature |
| :--- | :--- | :--- | :--- | :--- |
| **EX-31.1 / 31.2** (SOX 302 Certification) | `Form 10-K`, `Form 10-Q`, `Form 20-F`, `Form 10-D` | `I, [Name], certify that: 1. I have reviewed this annual report on Form 10-K of [Company]...` | Triggers high-weight token `"Form 10-K"` on Line 3. | **Subject vs. Referent Rule**: EX-31 treats the form as a passive direct object (`reviewed this report on Form 10-K`). Exhibits contain first-person grammar (`I, [Name], certify that:`); primary forms are institutional third-person. |
| **EX-32.1** (SOX 906 Certification) | `Form 10-K`, `Form 10-Q`, `Form 20-F` | `In connection with the Annual Report of [Company] on Form 10-K for the period ended [Date]...` | Triggers `"Annual Report on Form 10-K"` on Line 2. | **Accompaniment Clause**: Cites `18 U.S.C. Section 1350` and states `In connection with... as filed with the SEC`. Primary forms never qualify themselves as "in connection with" themselves. |
| **EX-24** (Power of Attorney) | `Forms 3, 4, and 5`, `Form 144`, `Schedule 13D`, `Schedule 13G` | `...to execute for and on behalf of the undersigned Forms 3, 4 and 5 in accordance with Section 16(a)...` | Triggers form tokens for insider trading (`Form 3`, `Form 4`, `Form 5`). | **Grant of Agency Rule**: Form tokens appear inside an infinitive grant (`to execute... Forms 3, 4 and 5`); the document opens with `POWER OF ATTORNEY` and `Know all by these presents`. |
| **EX-16.1** (Auditor Change Letter) | `Form 8-K`, `Form 8-K/A` | `We have read the statements made by [Company] pursuant to Item 4.01 of Form 8-K...` | Triggers `"Form 8-K"` in the first paragraph. | **External Intermediary Header**: Addressed to `Securities and Exchange Commission` on CPA firm letterhead (`We agree with the statements concerning our firm`). |
| **EX-7** (Auditor Non-Reliance Letter) | `Form 8-K` | `We have read the statements made by [Company] pursuant to Item 4.02 of Form 8-K...` | Triggers `"Form 8-K"` in the first paragraph. | **Non-Reliance Assertion**: Cites `Item 4.02` regarding financial restatement or non-reliance on audit report. |
| **EX-107** (Filing Fee Table) | `Form S-1`, `Form S-3`, `Form S-8`, `Form S-11`, `Form F-1`, `Form F-3` | `Calculation of Filing Fee Tables
Form S-3 (Form Type)
[Company Name]...` | Triggers the specific registration form type on Line 3. | **Structured Fee Metadata**: The form token is followed by `(Form Type)` or `Table 1: Newly Registered and Carry Forward Securities`. |
| **EX-36** (ABS Shelf Certification) | `Form SF-3` | `Certification for shelf offerings of asset-backed securities pursuant to General Instruction I.B.1.(a) of Form SF-3...` | Triggers `"Form SF-3"`. | **Certification Formula**: Cites `General Instruction I.B.1.(a)` and `characteristics of the securitized assets`. |
| **EX-4.C** (Description of Securities) | `Form 10-K` | `...incorporated by reference as an exhibit to the Annual Report on Form 10-K of which this Exhibit 4 is a part...` | Triggers `"Form 10-K"` in lines 5–15. | **FAST Act Title Anchor**: Titled `DESCRIPTION OF THE REGISTRANT'S SECURITIES REGISTERED PURSUANT TO SECTION 12`. |
| **EX-99.1** (Earnings Press Releases) | `Form 10-K`, `Form 10-Q`, `Form 8-K` | `More information will be provided in our Annual Report on Form 10-K...` | Contains cross-references to future 10-K/10-Q periodic filings. | **Media Dateline Header**: Opens with `FOR IMMEDIATE RELEASE` and city/state dateline (`[CITY] — [DATE] — [Company] today announced`). |

---

## 3. Dimension 2: Identity & Structural Subsumption Collisions

In several critical SEC scenarios, an exhibit **is an actual SEC form** or **subsumes an entire standalone periodic report**:

### 1. Exhibit 25 IS Form T-1
- **Statutory Provision**: 17 CFR § 229.601(b)(25).
- **Collision Nature**: Exhibit 25 is not an informal agreement; it is literally **Form T-1** (Statement of Eligibility of Trustee under the Trust Indenture Act of 1939).
- **Exact Document Header**:
  ```text
  SECURITIES AND EXCHANGE COMMISSION
  Washington, D.C. 20549
  FORM T-1
  STATEMENT OF ELIGIBILITY UNDER THE TRUST INDENTURE ACT OF 1939
  OF A CORPORATION DESIGNATED TO ACT AS TRUSTEE
  ```
- **Disambiguation**: Although it bears an SEC Form title (`FORM T-1`), it functions as an exhibit attached to a registration statement (Form S-1, S-3, S-4). It is distinguished by its institutional trustee disclosures (banking charter, Comptroller of the Currency supervision, and trustee capital surplus).

### 2. Exhibit 13.B & Exhibit 99.1 Can BE a Form 10-K or Form 10-Q
- **Statutory Scenario A (Item 601(b)(13)(ii))**: An issuer incorporating financial information into a Securities Act registration statement (e.g. Form S-4 merger proxy) must file the incorporated annual or quarterly report as Exhibit 13.
- **Statutory Scenario B (Regulation S-X Rule 3-05 / Rule 3-09 via EX-99.1)**: When a registrant completes a significant business acquisition, it must file the historical audited financial statements of the target company. If the target was already an SEC-reporting entity, the registrant frequently files the target's **entire original Form 10-K or Form 10-Q as Exhibit 99.1** to a Form 8-K (Item 9.01) or Form S-4!
- **Collision Nature**: The exhibit file itself begins with:
  ```text
  UNITED STATES SECURITIES AND EXCHANGE COMMISSION
  Washington, D.C. 20549
  FORM 10-K
  [X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934
  ```
- **Disambiguation**: The document *is* a complete Form 10-K, but its **operational role** within the current submission is `target_role = "supporting_exhibit"`. Pipelines must check submission metadata (`<DOCUMENT><TYPE>EX-99.1` or `<TYPE>EX-13`) to prevent overriding the registrant's primary 8-K/S-4 filing metadata.

### 3. Exhibits 102 & 103 on Form ABS-EE
- **Statutory Scenario**: In asset-backed securitizations, Form ABS-EE is an SEC form dedicated solely to transmitting electronic exhibits.
- **Collision Nature**: The filing header reads `FORM FOR SUBMISSION OF ELECTRONIC EXHIBITS FOR ASSET-BACKED SECURITIES (FORM ABS-EE)`, directly citing Exhibit 601(b)(102) (Asset Data File) and Exhibit 601(b)(103) (Asset Related Documents).

---

## 4. Dimension 3: Identifier & Namespace Numbering Collisions

When pipelines store exhibit identifiers as plain numbers, string matching creates namespace collisions with SEC Form types:

| Number / Token | Exhibit Type (Item 601) | Clashing SEC Form Name | Nature of Collision & Risk in ETL Pipelines |
| :---: | :--- | :--- | :--- |
| **1** | Underwriting Agreement | **Form 1** (Application for Exchange Registration) | String match `Form 1` vs `Exhibit 1` in legacy filing indices. |
| **3** | Articles of Incorporation / Charter | **Form 3** (Initial Statement of Beneficial Ownership) | Parsing `3` without prefix matches Section 16 insider forms. |
| **4** | Instruments Defining Rights / Indentures | **Form 4** (Statement of Changes in Beneficial Ownership) | Severe collision: thousands of Form 4 filings are submitted daily. |
| **5** | Legal Opinion re Legality | **Form 5** (Annual Statement of Beneficial Ownership) | Section 16 ownership annual filing matches Exhibit 5 integer. |
| **8** | Tax Opinion | **Form 8-K** (Current Report) / **Form 8-A** | In sloppy regexes, `8` triggers both Form 8-K and Exhibit 8. |
| **10** | Material Contracts | **Form 10** (General Exchange Act Registration) / **10-K** | Form 10 is an actual primary form; Exhibit 10 is a contract. |
| **13** | Annual/Quarterly Shareholder Report | **Schedule 13D / 13G** (Beneficial Ownership > 5%) | Number 13 matches Williams Act beneficial ownership filings. |
| **14** | Code of Ethics | **Schedule 14A (DEF 14A)** (Proxy Statement) | Number 14 matches proxy solicitation schedules. |
| **20** | Statements to Security Holders | **Form 20-F** (Foreign Private Issuer Annual Report) | In integer schemas, Exhibit 20 collides with Form 20-F. |
| **25** | Statement of Eligibility of Trustee (Form T-1) | **Form 25** (Delisting / Deregistration Notification) | Exhibit 25 is Form T-1; Form 25 is an exchange delisting notice. |

---

## 5. Formal Disambiguation Architecture for NLP Classifiers

To ensure clean document separation without tag dependency, the NLP evaluator enforces a four-stage classification cascade:

```
[Raw Ingested Text]
       │
       ▼
Stage 1: Primary Cover Form Gatekeeper
   Check for:
   • "[X] ANNUAL/QUARTERLY/CURRENT REPORT PURSUANT TO"
   • "Indicate by check mark whether the registrant"
   • "UNITED STATES SECURITIES AND EXCHANGE COMMISSION" (as document header)
   If MATCH: Classify as PRIMARY_COVER_FORM (Exclude from exhibit parsers)
       │
       ▼ (If NO match, document is candidate exhibit)
Stage 2: Lexical Self-Reference Sanitizer
   Check if "Form 10-K", "Form 8-K", "Form 20-F", or "Form 4" appear inside:
   • Passive object recitals ("reviewed this report on Form 10-K") -> Flag SOX 302
   • Accompaniment phrases ("In connection with Form 10-K...") -> Flag SOX 906
   • Item cross-references ("pursuant to Item 4.01 of Form 8-K") -> Flag EX-16 / EX-7
   • Power of Attorney grant ("to execute Forms 3, 4, 5") -> Flag EX-24
       │
       ▼
Stage 3: Substantive Structural Header Evaluation
   Apply invariant n-gram / anchor regexes (Lines 1–10)
   (e.g., "CERTIFICATE OF INCORPORATION", "INDENTURE", "CREDIT AGREEMENT")
       │
       ▼
Stage 4: Authority-Qualified Output
   Emit canonical tuple:
   (Authority="ITEM_601"|"FORM_20F", ExhibitCode, Subtype, Confidence)
```

---

## 6. Multi-Link Evidence Corpus Demonstrating Collisions

Below are verified SEC EDGAR filings illustrating these exact collision scenarios in live filings:

| Collision Type | Exhibit / Form Examined | Registrant Name | CIK | Accession Number | SEC EDGAR Link |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Lexical Self-Reference** | EX-31.1 referencing Form 10-K | Apple Inc. | 0000320193 | 0001193125-12-444068 | [Apple EX-31.1 (Cites Form 10-K)](https://www.sec.gov/Archives/edgar/data/320193/000119312512444068/d411355dex311.htm) |
| **Lexical Self-Reference** | EX-32.1 referencing Form 10-K | Microsoft Corporation | 0000789019 | 0001193125-26-323660 | [Microsoft EX-32.1 (Cites Form 10-K)](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-ex32_1.htm) |
| **Lexical Self-Reference** | EX-24 referencing Forms 3, 4, 5 | Camden Property Trust | 0001020941 | 0000950170-25-000402 | [Camden Property EX-24 (Cites Forms 3, 4, 5)](https://www.sec.gov/Archives/edgar/data/1020941/000095017025000402/cpt-ex24.htm) |
| **Lexical Self-Reference** | EX-16.1 referencing Form 8-K | Alteryx, Inc. | 0001689923 | 0001193125-19-016035 | [Alteryx EX-16.1 (Cites Form 8-K)](https://www.sec.gov/Archives/edgar/data/1689923/000119312519016035/d669577dex161.htm) |
| **Lexical Self-Reference** | EX-107 referencing Form S-3 | Silk Road Medical, Inc. | 0001397702 | 0001397702-23-000037 | [Silk Road Medical EX-107 (Cites Form S-3)](https://www.sec.gov/Archives/edgar/data/1397702/000139770223000037/silk-20230509xex10_7.htm) |
| **Subsumption / Identity** | EX-25 IS Form T-1 | Citigroup Inc. | 0000015615 | 0001193125-10-268831 | [Citigroup EX-25 (Form T-1 Header)](https://www.sec.gov/Archives/edgar/data/15615/000119312510268831/dex251.htm) |
| **Subsumption / Identity** | EX-25 IS Form T-1 | The Hershey Company | 0000047111 | 0000047111-21-000039 | [Hershey EX-25 (Form T-1 Header)](https://www.sec.gov/Archives/edgar/data/47111/000004711121000039/exhibit251-formtx1statement.htm) |
| **Subsumption / Full Report** | EX-99.1 Subsumes Form 10-K/Q | American Honda Receivables | 0000890975 | 0001104659-23-061771 | [American Honda Form 8-K EX-99.1](https://www.sec.gov/Archives/edgar/data/890975/000110465923061771/tm2314760d1_8k.htm) |
| **Authority Collision** | Form 20-F Ex 1 vs Item 601 Ex 1 | CRH public limited company | 0000849395 | 0001193125-21-078969 | [CRH Form 20-F Ex 1 (Articles, not Underwriting)](https://www.sec.gov/Archives/edgar/data/849395/000119312521078969/d911751dex1.htm) |
| **Authority Collision** | Form 20-F Ex 8 vs Item 601 Ex 8 | Vale S.A. | 0000917851 | 0000950123-09-007362 | [Vale Form 20-F Ex 8 (Subsidiaries, not Tax)](https://www.sec.gov/Archives/edgar/data/917851/000095012309007362/y75715exv8.htm) |
| **Authority Collision** | Form 20-F Ex 13 vs Item 601 Ex 13 | ReNew Energy Global plc | 0001848763 | 0001193125-26-325073 | [ReNew Form 20-F Ex 13 (SOX 906, not Annual Report)](https://www.sec.gov/Archives/edgar/data/1848763/000119312526325073/rnw-ex13_1.htm) |

