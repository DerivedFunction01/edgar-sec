# `edgar_sec/domain/` — Layer 1: value objects, vocabulary, and schema contracts

Layer 1 holds the facts every other layer agrees on and none of them may
specialise: identity primitives, EDGAR URL shapes, statutory vocabulary, Arrow
schemas, and the frozen dataclasses that cross layer boundaries. It performs no
IO, opens no files, and reaches no network.

## Purpose

`edgar_sec/domain/` is the only place a value may be *defined* rather than
*produced*. A CIK, a form family, a cover-page label, a dataset column list: all
of it is declared here once, and `infra`, `engine`, and `pipelines` import
downward. What this layer is not: it does not fetch, persist, parse, classify, or
schedule. A rule that needs a request, a file handle, a thread, or a stage
counter belongs above this layer.

## Layer map

Layer 1 may import **only from `edgar_sec.foundation`** — never from `infra`,
`engine`, or `pipelines`. The layer's edges to `foundation` are exactly two
modules: `edgar_sec/foundation/regex/builder.py` (`build_alternation`, used by
`forms/vocabulary.py:12` and `forms/checkmarks.py:9`) and
`edgar_sec/foundation/hashing.py` (`sha256_text`, used by
`document/models.py:10`). The only other imports are `pyarrow` in the two
`schemas.py` modules, and five same-layer imports
(`filing_catalog/schemas.py` → `sec_urls` and `submissions.schemas`;
`submissions/models.py` and `document/models.py` → `identity`;
`document/acquisition.py` → `document.models`;
`taxonomy/family_vocab.py` and `taxonomy/legal_forms.py` →
`taxonomy.jurisdictions`). An Arrow type reaches a contract here without the
storage engine ever being involved.

| Package | Owns |
| :--- | :--- |
| `edgar_sec/domain/document/` | Document locators, occurrence provenance, acquisition result records, flat block stream |
| `edgar_sec/domain/filing_catalog/` | Catalog Arrow schemas, version constants, and the filter vocabulary shared by planning and selection |
| `edgar_sec/domain/forms/` | Cover and form vocabulary, checkmark tokens, form-family aliases, checkbox schemas, body evidence tiers, evaluator decisions |
| `edgar_sec/domain/submissions/` | The `submission_metadata` Arrow schema and its in-memory DTOs |
| `edgar_sec/domain/taxonomy/` | Jurisdictions, legal-form suffixes, and company-family lexical tables |
| `edgar_sec/domain/identity.py` | `Cik`, `AccessionNumber` |
| `edgar_sec/domain/sec_urls.py` | EDGAR URL construction and archive-URL parsing |

Enforcement is mechanical: the `layer-boundary` scanner
(`edgar_sec/foundation/scanners/layers.py`) walks every `edgar_sec/**/*.py` with
`ast`, resolves the callee layer from the import path, and fails the build when
`callee_rank > caller_rank`. `check.py --scan` reports `layer-boundary: clean`
today.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `identity.py` | `Cik` rejects any value outside `0..9_999_999_999` and renders as a 10-digit zero-padded string via `to_10digit()`; `AccessionNumber` holds the `^\d{10}-\d{2}-\d{6}$` form, accepts either EDGAR spelling via `from_any()`, and exposes the unhyphenated form as `.normalized` |
| `sec_urls.py` | The only place an EDGAR URL is assembled or parsed. Declares `SEC_SUBMISSIONS_BASE`, `SEC_ARCHIVE_BASE`, `submissions_url()`, `historical_submissions_url()`, `archives_url()`, `parse_archive_url()`, `full_submission_url_for()` |
| `document/models.py` | `DocumentLocator`, `FilingOccurrence`, `RawDocumentBlob`, `NormalizedDocument`, `NormalizationFailure`, and the two key-derivation functions |
| `document/acquisition.py` | `FetchResult`, `AcquisitionFailure`, `FetchStatus`, and `is_stub_document_path()` |
| `document/blocks.py` | `BlockKind`, `DocumentBlock`, `BlockStream` — the flat 1D typed block representation |
| `filing_catalog/schemas.py` | `TARGET_SCHEMA`, `PROFILE_SCHEMA`, the three version constants, and the three column tuples |
| `filing_catalog/filters.py` | `DEFAULT_DOCUMENT_SUFFIXES`, `normalize_suffixes()` |
| `forms/vocabulary.py` | Cover label aliases, filer-status constants, checkbox keyword grids, value patterns, and the eight compiled field-label regexes |
| `forms/checkmarks.py` | Checkmark tokens, bracket/symbol boundaries, font-glyph mappings, and the `CHECKMARK_MARK_RE` scan pattern |
| `forms/schemas.py` | `CheckboxConstraint`, `CoverCheckboxSchema`, and the seven `STATUTORY_CHECKBOX_CONSTRAINTS` |
| `forms/families.py` | `FORM_FAMILY_ALIASES` and the `form_family` / `resolve_alias` / `normalize_form` / `aliases_for_family` lookup API |
| `forms/body_evidence.py` | Tiers of body-prose vocabulary used to end the cover region |
| `forms/decisions.py` | `DecisionAction` and `EvaluatorDecision` |
| `submissions/schemas.py` | `SUBMISSION_METADATA_SCHEMA` and its six nested struct definitions |
| `submissions/models.py` | `EntityProfile`, `SubmissionsAggregate`, `Address`, `FormerName`, `Listing`, `FilingRecord` |
| `taxonomy/jurisdictions.py` | `STATE_POSTAL_CODES`, `STATE_NAMES`, `JURISDICTION_RE`, `strip_jurisdiction()`, `clean_entity_name()` |
| `taxonomy/legal_forms.py` | `LEGAL_FORMS`, `NAME_STOPWORDS`, `entity_name_tokens()` |
| `taxonomy/family_vocab.py` | `ABBR_MAP`, `CONTEXT_RULES`, `PLURAL_MAP`, `ROMAN`, `PLACEHOLDER`, `STATE_CODES`, and the five family-resolution tuning constants |

The five `__init__.py` files in this layer are one-line docstrings. No symbol is
re-exported from any of them; consumers import from the leaf module
(`from edgar_sec.domain.identity import Cik`), per `AGENTS.md` §1.2.

## Contracts

**Guarantees this layer makes.**

- A value is defined once. `Cik`, `AccessionNumber`, the form-family alias
  table, the Arrow column lists, and the filter vocabularies each have a single
  owning module; consumers read them rather than restating them.
- Vocabulary tables are immutable. `taxonomy/family_vocab.py` uses
  `MappingProxyType` for mappings and `frozenset` for membership and neighbour
  sets, and `taxonomy/jurisdictions.py` uses `frozenset`, so no caller can
  corrupt the vocabulary for the process and make a result depend on call order.
- Compiled patterns are deterministic. `taxonomy/jurisdictions.py:136` builds
  its alternation in `sorted()` order so the pattern is byte-identical on every
  run and across processes.
- Regex construction goes through the DSL. Hand-written three-branch alternation
  literals are banned by the `regex-alternations` scanner, whose exemption list
  is only `edgar_sec/foundation/regex/` and `edgar_sec/foundation/text/`
  (`scanners/regex_alternations.py:46-49`) — this layer is scanned, not exempt.
- No side effects. A scan of `edgar_sec/domain/**.py` for `open(`, `Path(`,
  `os.`, `urllib`, `socket`, `subprocess`, and `duckdb` returns exactly one hit,
  and it is the word `duckdb` inside a docstring in `filing_catalog/filters.py:16`.

**Obligations callers place on this layer.**

- Import downward only. The scanner rejects any import whose callee layer ranks
  above the caller's.
- Do not treat a dataclass as a place to hang behaviour. `document/models.py`
  imports `acquisition.is_stub_document_path` inside the `is_stub_path` property
  body (`models.py:84`) to break the `acquisition → models` cycle; that deferred
  import is the only structural concession in the layer, and it exists because
  `acquisition.py` already imports `DocumentLocator` at module scope.
- Bump the version constant, not the column list, when a schema changes.
  `SCHEMA_VERSION`, `TARGET_SCHEMA_VERSION`, and `PROFILE_SCHEMA_VERSION` exist
  for exactly that (`filing_catalog/schemas.py:22-25`).

## Public surface

- `Cik`, `AccessionNumber` — `edgar_sec/domain/identity.py`.
- `SEC_SUBMISSIONS_BASE`, `SEC_ARCHIVE_BASE`, `CIK_PADDED_WIDTH`,
  `submissions_url`, `historical_submissions_url`, `archives_url`,
  `normalize_cik`, `normalize_accession`, `accession_hyphenated`,
  `ArchiveUrlParts`, `parse_archive_url`, `full_submission_url_for` —
  `edgar_sec/domain/sec_urls.py`.
- The per-package surfaces are documented in each subpackage README:
  [document](document/README.md), [filing_catalog](filing_catalog/README.md),
  [forms](forms/README.md), [submissions](submissions/README.md),
  [taxonomy](taxonomy/README.md).

Every module publishes an explicit `__all__`. That is an export *list*, not a
re-export: it does not import anything, and it is the only mechanism by which a
name in this layer becomes visible to another module.

## Tests

```text
tests/domain/test_identity.py                 tests/domain/document/test_models.py
tests/domain/test_sec_urls.py                 tests/domain/document/test_acquisition.py
tests/domain/test_sec_urls_archive.py         tests/domain/document/test_blocks.py
                                             tests/domain/filing_catalog/test_schemas.py
                                             tests/domain/filing_catalog/test_filters.py
                                             tests/domain/forms/test_checkmarks.py
                                             tests/domain/forms/test_decisions.py
                                             tests/domain/forms/test_families.py
                                             tests/domain/forms/test_schemas.py
                                             tests/domain/submissions/test_schemas.py
                                             tests/domain/taxonomy/test_taxonomy.py
```

Fourteen test files, 91 test functions, against 18 source modules. `sec_urls.py`
is split across two mirrored test files (`test_sec_urls.py`, 8 functions;
`test_sec_urls_archive.py`, 11) rather than one per §6.3.

## Deliberate gaps

- **`domain/records.py` does not exist, and the roadmap still lists it as
  Pending.** `roadmap/refactor_v2/v2_refactor_roadmap.md:232` targets
  `domain/records.py` as the destination for `DocumentLocator`,
  `FilingOccurrence`, and `DocumentOccurrenceResult`, status **Pending (Phase
  2.5)**. The two record types exist instead at
  `edgar_sec/domain/document/models.py`, and `DocumentOccurrenceResult` has no v2
  counterpart at all — the acquisition result it corresponds to is
  `FetchResult` in `document/acquisition.py`. The roadmap's target path is
  therefore stale relative to the code, not a missing capability.
- **`compare_sources` was dropped without a record on the v2 side.** The
  roadmap's relocation matrix marks `phases/01/.../registry.py → domain/identity.py`
  **Built** (`:234`), and its own doc-claim audit records that as
  "doc stale — undocumented drop" (`:1250`): there is no `effective_cik_input.csv`,
  registrant registry, or `cik_diff.json` anywhere in `edgar_sec/`, and
  `domain/identity.py` holds only the two value objects. The replacement is the
  per-invocation `RunOptions` in `pipelines/metadata_sync/cli.py`, not a
  persisted project config.
- **The v1 dual identity implementation is a recorded divergence, not a
  superseded design.** v1 shipped two competing filing-identity schemes. v2
  adopted the `sha256(accession + ":" + document_path)` form, which
  `document/models.py:23` implements as `derive_document_locator_key()` and
  `infra/storage/duckdb_catalog.py:155` implements in SQL, pinned by
  `tests/pipelines/filing_catalog/test_phase25_contract.py`. v1's other scheme —
  canonical JSON hashed under a `filing-identity-v1` domain prefix, in
  `.v1/defs/filing_identity.py` — was **not** adopted.
  `roadmap/refactor_v2/v1_retirement.tsv:6` marks that v1 file `NEEDS_EVIDENCE`
  with the reason "Deleting it destroys the only record of the alternative
  scheme", and `v2_refactor_roadmap.md:1376-1380` repeats it as a deliberate
  exception to the deletion policy. Do not describe the canonical-JSON scheme as
  deprecated: it is the surviving record of the alternative v2 declined.
- **`sec_urls.py` and `identity.py` are separate modules with separate jobs, and
  their split is not a seam you may quietly move across.** `identity.py` owns
  the value objects; `sec_urls.py` owns the URL shapes. `roadmap/refactor_v2/phase_2.md:726-737`
  records why `sec_urls.py` sits in Layer 1 rather than `infra`: the catalog
  schemas need `SEC_ARCHIVE_BASE` for the SQL fallback, and Layer 1 may not
  import Layer 2.
- **The `layer-boundary` scanner does not check for cycles.** It flags only
  `callee_rank > caller_rank` (`scanners/layers.py:86`), so a same-layer cycle
  or an intra-package cycle is invisible to it. `AGENTS.md` §1 calls the graph
  acyclic; that property is currently maintained by convention within a layer,
  not enforced by the scanner.
- **`SEC_ARCHIVE_BASE` is re-exported through `filing_catalog/schemas.py`.** It
  appears in that module's `__all__` and `infra/storage/duckdb_catalog.py:32`
  imports it from there rather than from `sec_urls`. This is a module-level
  re-export, not an `__init__.py` barrel, so it does not breach §1.2 — but the
  canonical import is `from edgar_sec.domain.sec_urls import SEC_ARCHIVE_BASE`.
