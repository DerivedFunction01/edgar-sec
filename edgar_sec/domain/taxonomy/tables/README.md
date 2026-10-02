# `edgar_sec/domain/taxonomy/tables/` — Declarative Table Taxonomy Specifications

Pure declarative models, 2D geometric constraints, and the master registry of table family
specifications for financial statements, regulatory schedules, and cover layouts.

## Purpose

Declares what each table family *looks like* — its vocabulary evidence, its geometric
bounds, its repair policy, and its scope — and nothing about how a candidate table is
scored against those declarations. That scoring is `engine/tables/taxonomy/classifier.py`.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `shapes.py` | `ShapeConstraint` — min/max rows and columns, numeric-density bounds, average cell width |
| `specs.py` | `TableScope`, `RepairPolicy`, `VocabularyEvidence`, `FamilyMatch`, `FamilyClassification`, `TableFamilySpec`, `build_ngram_tier()` |
| `families.py` | `FAMILY_SPECS` — the 22-family master registry, assembled from the statement specs, the schedule specs, and the cover component specs |

## Contracts

- **Layer-1 purity:** pure data definitions and compiled evidence packs, with no internal
  dependency on Layer 2, 3, 4, or 5. `families.py` imports downward only into
  `domain/taxonomy/statements/`, `domain/taxonomy/schedules/`, and
  `domain/taxonomy/components/`.
- **Immutability:** `ShapeConstraint`, `VocabularyEvidence`, `FamilyMatch`,
  `FamilyClassification`, and `TableFamilySpec` are all frozen slotted dataclasses.
  `TableScope` and `RepairPolicy` are string enums, which are equally immutable.
- **Orthogonality:** every family declares unigram veto terms, so a family cannot claim a
  line that belongs to another.
- **One ordering source.** `families.py` is the only place a family is named; both the
  classifier and the mirrored test iterate its keys rather than keeping their own list.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `ShapeConstraint` | `shapes.py` |
| `TableScope` (`BODY`, `TOC`, `COVER`), `RepairPolicy`, `VocabularyEvidence`, `FamilyMatch`, `FamilyClassification`, `TableFamilySpec`, `build_ngram_tier()` | `specs.py` |
| `FAMILY_SPECS` (22 families), `TableFamilySpec` (re-exported) | `families.py` |

No command surface.

## Tests

```text
tests/domain/taxonomy/tables/test_specs.py
```

## Deliberate gaps

- **Two of three modules have no mirrored test.** `test_specs.py` imports `FAMILY_SPECS`
  and `ShapeConstraint`, so it exercises all three, but `AGENTS.md` §6.3 asks for a test
  file per source module at the mirrored path: `test_shapes.py` and `test_families.py` are
  absent. The registry itself is pinned (22 families, and a per-family invariant loop).
- **No execution and no zone scoring.** Algorithmic zone scoring and family classification
  live in `engine/tables/taxonomy/classifier.py`, which reads `FAMILY_SPECS` and is the only
  production consumer.
- **The v1 probe CLI has no v2 counterpart.** v1's `defs/taxonomy/` shipped a table probe;
  nothing under `domain/` or `engine/tables/` exposes one.
- **`families.py` re-exports `TableFamilySpec`.** It is in that module's `__all__` even
  though `specs.py` owns the class. This is a module-level re-export rather than an
  `__init__.py` barrel, so it does not breach `AGENTS.md` §1.2, but the owning module is
  `edgar_sec/domain/taxonomy/tables/specs.py`.
- **`families.py` is a plain dict, not a frozen mapping.** `FAMILY_SPECS` is mutable, unlike
  the vocabulary tables in `domain/taxonomy/{jurisdictions,legal_forms,family_vocab}.py`.
  Its *values* are frozen, so a caller cannot corrupt a spec, but it can add or remove a
  family.