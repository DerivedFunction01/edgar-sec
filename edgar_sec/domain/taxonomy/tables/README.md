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
| `specs.py` | The spec, match, classification, and evidence types, the scope and repair-policy enums, and the n-gram tier builder |
| `families.py` | `FAMILY_SPECS` — the master registry, assembled from the statement specs, the schedule specs, and the cover component specs |

## Contracts

- **Immutability:** the spec, match, classification, and evidence types are frozen
  slotted dataclasses, and the scope and repair-policy types are string enums.
- **Exclusion terms are advisory, so orthogonality is best-effort.** A family whose
  evidence pack carries an empty `exclusions` set can claim a line that belongs to
  another family. Read the owning module's pack rather than assuming two families
  are mutually exclusive.
- **One ordering source.** A family becomes real when it is listed in
  `FAMILY_SPECS`; the classifier and its mirrored test iterate the registry rather
  than a second list, so a spec absent from the registry is invisible to both.

## Public surface

- `FAMILY_SPECS`, the registry every family is reached through — `families.py`.
- `TableFamilySpec`, `VocabularyEvidence`, `FamilyMatch`, `FamilyClassification`,
  `TableScope`, `RepairPolicy`, and the n-gram tier builder — `specs.py`.
- `ShapeConstraint` — `shapes.py`.

No command surface.

## Tests

Tests mirror this package under `tests/domain/taxonomy/tables/`.

## Deliberate gaps

- **No way to probe a classification.** Nothing in the repository exposes a command
  that reports how a candidate table scores against `FAMILY_SPECS`; to see a
  classification you must call the engine classifier in-process.
- **`FAMILY_SPECS` is a mutable dict.** Its specs are frozen, so a caller cannot
  corrupt one, but a caller can add or remove a family. Treat the registry as
  read-only.
