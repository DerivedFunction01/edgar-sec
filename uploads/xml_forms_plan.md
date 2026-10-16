# XML-Based SEC Forms Architecture & Common Extraction Plan

Companion engineering plan to [uploads/form_cover_profile_playbook.md](form_cover_profile_playbook.md), detailing the XML-based filing landscape across [uploads/sec_forms/](sec_forms/), modern electronic XML schemas versus legacy HTML-to-XML pipelines, and the factoring of shared modules (signatures, statutory boilerplate, and entity parsing).

---

## 1. Executive Summary & Problem Framing

Modern EDGAR filings increasingly mandate structured, machine-readable XML schemas, while historical archives (and occasional filer errors) contain unstructured or tabular HTML/ASCII presentations. 

Following the implementation of Form 4 (`ownershipDocument` XML schema and pre-2003 HTML-to-XML converter), this document:
1. **Audits all forms in `uploads/sec_forms/`** to classify which require an XML-based acquisition and rendering pipeline.
2. **Defines modern vs. legacy XML requirements** for each target family.
3. **Identifies repetitive patterns** (signatures, corporate roles, jurats, statutory warnings, OMB control blocks, and address/tax grids) currently confined to `ownership/`.
4. **Outlines a refactoring architecture** to factor these elements into reusable, layer-bounded domain and engine modules without breaking ongoing ownership work.

---

## 2. Landscape Audit: Forms Requiring XML Pipelines

Of the 20 form specifications in [uploads/sec_forms/](sec_forms/) and [uploads/exhibits.md](exhibits.md), the following forms mandate structured XML pipelines:

| Form Specification | Form Family / Description | Modern SEC XML Schema | Legacy Presentation Format | Required Pipeline Operation |
| :--- | :--- | :--- | :--- | :--- |
| [form3.md](sec_forms/form3.md) | **Form 3**: Initial Beneficial Ownership | `<ownershipDocument>` (X0508) | Tabular HTML / ASCII tables | `AcquisitionOperation.RENDER_TO_XML` |
| [form4.md](sec_forms/form4.md) | **Form 4**: Changes in Beneficial Ownership | `<ownershipDocument>` (X0508) | Tabular HTML / ASCII tables | `AcquisitionOperation.RENDER_TO_XML` *(Implemented)* |
| [form5.md](sec_forms/form5.md) | **Form 5**: Annual Beneficial Ownership | `<ownershipDocument>` (X0508) | Tabular HTML / ASCII tables | `AcquisitionOperation.RENDER_TO_XML` |
| [form144.md](sec_forms/form144.md) | **Form 144**: Proposed Sale of Securities | `<noticeOfProposedSaleOfSecurities>` | Multi-tier HTML / ASCII tables | `AcquisitionOperation.RENDER_TO_XML` |
| [formd.md](sec_forms/formd.md) | **Form D**: Notice of Exempt Offering | `<edgarSubmission>` / `<offeringData>` | 16-item Tabular HTML notice | `AcquisitionOperation.RENDER_TO_XML` |
| [form13f.md](sec_forms/form13f.md) | **Form 13F**: Institutional Holdings (HR/NT) | `<edgarSubmission>` / `<informationTable>` | 8-column ASCII text / HTML | `AcquisitionOperation.RENDER_TO_XML` |
| [schedule13d.md](sec_forms/schedule13d.md) | **Schedule 13D**: 5%+ Beneficial Ownership | `<schedule13D>` (Mandated 2024) | HTML narrative + 14-row Matrix | Hybrid (Matrix XML + Narrative txt) |
| [schedule13g.md](sec_forms/schedule13g.md) | **Schedule 13G**: Passive Ownership | `<schedule13G>` (Mandated 2024) | HTML narrative + Cover Matrix | Hybrid (Matrix XML + Narrative txt) |
| [exhibits.md](exhibits.md) (EX-107) | **EX-107**: Structured Filing Fee Tables | `<fee_tables>` / Rule 107 XML | Unstructured HTML fee tables | `AcquisitionOperation.RENDER_TO_XML` |

### Non-XML Forms in `uploads/sec_forms/` (Text / Cover Profiles Only)
- **Periodic Reports**: [10-k.md](sec_forms/10-k.md), [10-q.md](sec_forms/10-q.md), [20-f.md](sec_forms/20-f.md). (Text/iXBRL narratives; target is `render_to_txt`).
- **Current Reports**: [8-k.md](sec_forms/8-k.md), [6-k.md](sec_forms/6-k.md). (Item-driven narrative events; target is `render_to_txt`).
- **Proxy Statements**: [def14a.md](sec_forms/def14a.md). (Narrative governance materials).
- **Registration Statements**: [forms-1.md](sec_forms/forms-1.md), [forms-3.md](sec_forms/forms-3.md), [forms-4.md](sec_forms/forms-4.md), [forms-8.md](sec_forms/forms-8.md). (Prospectuses; target is `render_to_txt`).
- **Notifications & Filings**: [form12b-25.md](sec_forms/form12b-25.md) (NT), [form15.md](sec_forms/form15.md) (Termination). (Short narrative cover profiles).

---

## 3. Deep-Dive on Target XML Forms

### A. Section 16 Ownership Forms (Forms 3, 4, 5)
- **Shared XML Root**: `<ownershipDocument>`
- **Structural Differences**:
  - **Form 3**: Initial holdings only. Table I (Non-Derivative Holdings) and Table II (Derivative Holdings) contain no transaction codes, dates, or prices; only title of security, amount owned, and ownership form (Direct/Indirect).
  - **Form 4**: Active transactions. Includes Box 1(b) and 10b5-1 checkmarks, transaction codes (P, S, M, A, etc.), transaction dates, and prices.
  - **Form 5**: Annual reconciliation. Includes Box 1(b) (prior Form 4/5 obligations) and Box 2 checkmarks (Form 3/4 transactions not reported), plus deferred transaction codes (G, W, Z, etc.).
- **Common Engine**: Both Form 3 and Form 5 can reuse the existing `edgar_sec/engine/forms/ownership/` table grid and cell resolution logic with minor schema branches.

### B. Form 144 (Notice of Proposed Sale of Securities)
- **Mandate**: Mandated electronic XML submission since April 13, 2023 (SEC Release 33-11070).
- **XML Root**: `<noticeOfProposedSaleOfSecurities>`
- **Legacy Problem**: Prior to April 2023, filed as filer-authored HTML tables.
- **Key Subsections**:
  - `issuerInformation`: Name, SEC file number, CIK, address, phone.
  - `personForWhoseAccountSold`: Name, relationship to issuer (officer, director, 10% owner).
  - `securitiesProposedToBeSold`: Broker/market maker, title of class, shares to sell, aggregate market value, outstanding shares, approximate sale date, exchange.
  - `tableI_securitiesToBeSold`: Acquisition date, nature of transaction, person from whom acquired, payment date, consideration.
  - `tableII_securitiesSoldPast3Months`: Date of sale, amount sold, gross proceeds.
  - `signatureAndRepresentations`: 10b5-1 plan adoption date, conformed signature, 18 U.S.C. 1001 caution.

### C. Form D (Notice of Exempt Offering of Securities)
- **Mandate**: Pure structured XML electronic filing mandated since March 16, 2009 (SEC Release 33-8891).
- **XML Root**: `<edgarSubmission>` with `<offeringData>`
- **Structure**: 16 standardized items:
  - Items 1–3: Issuer Identity, Principal Place of Business, Related Persons (Executive Officers, Directors, Promoters).
  - Items 4–6: Industry Group, Issuer Size (Revenue/NAV Range), Federal Exemptions (Rule 504, 506(b), 506(c), Section 4(a)(5)).
  - Items 7–11: Type of Filing, Duration, Security Types, Business Combination, Minimum Investment.
  - Items 12–16: Sales Compensation (Broker CRD, solicitation states), Offering/Sales Amounts (Total, Sold, Remaining), Investors (Accredited/Non-Accredited), Sales Commissions, Use of Proceeds.
  - Signatures & Terms of Submission: Issuer name, signature, signer name, title, date.

### D. Form 13F (Institutional Investment Manager Holdings)
- **Mandate**: Structured XML mandated since May 20, 2013; updated in 2023 for FIGI.
- **XML Root**: `<edgarSubmission>` with:
  - `<coverPage>`: Period ended, manager name, address, Form 13F file number (28-xxxx), report type (13F HOLDINGS REPORT, NOTICE, COMBINATION).
  - `<summaryPage>`: Other included managers count, table entry count, total table value.
  - `<informationTable>`: Repeating `<infoTable>` rows (`nameOfIssuer`, `titleOfClass`, `cusip`, `figi`, `value`, `sshPrnamt`, `sshPrnamtType`, `putCall`, `investmentDiscretion`, `otherManager`, `votingAuthority`).
- **Legacy Problem**: Pre-2013 filings are plain ASCII 8-column fixed-width tables.

### E. Schedules 13D & 13G (Beneficial Ownership)
- **Mandate**: Structured XML mandated under SEC Release 33-11253 (effective late 2024).
- **Structure**:
  - Cover Page Disclosure Matrix: 14 numbered rows (Filer Name, Group Member, Source of Funds, Citizenship, Voting Power [Sole/Shared], Dispositive Power [Sole/Shared], Aggregate Beneficial Ownership, Percent of Class, Type of Reporting Person).
  - Narrative Body: Items 1–7 (13D) or Items 1–10 (13G).
- **Pipeline Strategy**: Hybrid approach extracting structured XML for the Cover Disclosure Matrix while preserving the narrative body as clean normalized text.

---

## 4. Factoring Out Common Modules & Phrases

Substantial code in `edgar_sec/domain/forms/families/ownership/evidence.py` and `edgar_sec/engine/forms/ownership/patterns.py` can be factored into cross-form shared modules:

```text
edgar_sec/
├── domain/forms/common/
│   ├── signatures.py       <-- NEW: Shared models & lexical evidence for signatures
│   ├── statutory.py        <-- NEW: 18 U.S.C. 1001, OMB, procedural legal boilerplate
│   └── entities.py         <-- NEW: Filer/Issuer identity, address & tax ID tokens
└── engine/forms/common/
    ├── signatures.py       <-- NEW: Reusable signature, delegation, & conformed mark parser
    └── entities.py         <-- NEW: Street, city, state, zip, IRS, CIK regex extractors
```

### A. Signatures & Delegation Subsystem
Repeated across Forms 3, 4, 5, 144, D, 13F, 13D, 13G, and periodic reports:

1. **Conformed Markings**:
   - `/s/`, `\s\`, `/s`, `s/`, `[Signature]`, underline runs (`______`, `======`).
2. **Delegation Prefixes & Roles**:
   - `By:`, `For:`, `on behalf of`, `per`, `Power of Attorney`, `Attorney-in-Fact`, `POA`, `authorized signatory`, `duly authorized`.
3. **Corporate Officer Titles**:
   - `President`, `Vice President`, `Secretary`, `Corporate Secretary`, `Treasurer`, `Chief Executive Officer`, `Chief Financial Officer`, `Managing Member`, `General Partner`, `Trustee`, `Director`.
4. **Notary & Jurat Boilerplate**:
   - `Notary Public`, `Subscribed and sworn`, `Commission expires`, `My commission`, `State of`, `County of`, `SS.`.

**Factored Domain Model** (`domain/forms/common/signatures.py`):
```python
@dataclass(frozen=True, slots=True)
class Signatory:
    name: str
    title: str | None = None
    date: str | None = None
    delegation_kind: DelegationKind = DelegationKind.DIRECT
    agent_name: str | None = None

@dataclass(frozen=True, slots=True)
class SignatureBlock:
    signatories: tuple[Signatory, ...]
    is_conformed: bool = True
    has_notary: bool = False
```

### B. Statutory Warnings & Criminal Boilerplate
Repeated verbatim across Forms 3, 4, 5, 144, D:

1. **Federal Criminal Violations**:
   - `"Intentional misstatements or omissions of facts constitute Federal Criminal Violations. See 18 U.S.C. 1001 and 15 U.S.C. 78ff(a)."`
2. **OMB Control Notice**:
   - `"Potential persons who are to respond to the collection of information contained in this form are not required to respond unless the form displays a currently valid OMB control number."`
3. **Filing Copies & Procedural Boilerplate**:
   - `"File three copies of this Form, one of which must be manually signed. If space is insufficient, see Instruction 6 for procedure."`
   - `"SEC 1474"`, `"SEC 2474"`, `"(over)"`.

**Factored Domain Module** (`domain/forms/common/statutory.py`):
- Provides compiled veto regexes (`STATUTORY_BOILERPLATE_VETOES`) and cleanup masks so table parsers do not leak boilerplate into extracted data cells.

### C. Filer Identity, Address, and Tax ID Parsing
Repeated across all forms:
- `STATE_ZIP_RE`: State abbreviation + 5-digit/9-digit ZIP code.
- `IRS_RE`: 9-digit IRS employer/tax identification number (`XX-XXXXXXX`).
- `STREET_ANCHOR_TERMS`: `street`, `st`, `avenue`, `ave`, `boulevard`, `blvd`, `road`, `rd`, `suite`, `ste`, `floor`, `fl`.
- `TICKER_PAREN_RE`: Ticker and exchange patterns (e.g. `(NASDAQ: FOO)`).

---

## 5. Architectural Integration: Extensible XML Dispatcher

Currently, `edgar_sec/engine/forms/render.py` hardcodes Form 4:
```python
if target_op == AcquisitionOperation.RENDER_TO_XML:
    from edgar_sec.engine.forms.ownership.render_to_xml import render_form4_to_xml
    xml_bytes = render_form4_to_xml(raw_bytes)
    return xml_bytes.decode("utf-8", errors="replace")
```

### Proposed Generalized Dispatch Architecture:
1. **Renderer Registry** in `edgar_sec/engine/forms/xml/`:
   ```python
   XML_RENDERER_CATALOG: dict[str, Callable[[bytes], bytes]] = {
       "3": render_ownership_to_xml,
       "4": render_ownership_to_xml,
       "5": render_ownership_to_xml,
       "144": render_form144_to_xml,
       "D": render_formd_to_xml,
       "13F": render_form13f_to_xml,
   }
   ```
2. **Family Profile Registration**:
   Forms 144, D, and 13F register `AcquisitionOperation.RENDER_TO_XML` in `domain/forms/families/processing_profiles.py`.
3. **Zero Backward-Compatibility Shims**:
   Keep leaf import discipline and downward-only dependencies per `AGENTS.md`.

---

## 6. Implementation Phasing Roadmap

1. **Phase 1: Domain Factoring (Zero Risk, Non-Breaking)**
   - Create `edgar_sec/domain/forms/common/signatures.py` and `statutory.py`.
   - Create `edgar_sec/engine/forms/common/signatures.py`.
   - Update `ownership/evidence.py` and `ownership/patterns.py` to import from common, verifying against existing unit tests without changing logic.
2. **Phase 2: Complete Section 16 Suite (Forms 3 & 5)**
   - Extend `ownership/render_to_xml.py` to support Forms 3 and 5 schema variations.
   - Add test fixtures for historical Form 3 and Form 5 HTML filings.
3. **Phase 3: Form 144 XML Pipeline**
   - Implement `engine/forms/form144/` with HTML-to-XML converter for pre-2023 filings and native pass-through for modern filings.
   - Register Form 144 in `processing_profiles.py`.
4. **Phase 4: Form D & Form 13F XML Pipelines**
   - Implement Form D 16-item XML parser and Form 13F Information Table parser.
   - Connect to `review generate` and `review analyze` CLI workflows.
