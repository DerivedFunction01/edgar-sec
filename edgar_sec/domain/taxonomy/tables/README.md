# `edgar_sec/domain/taxonomy/tables/` — Declarative Table Taxonomy Specifications

Pure declarative models, 2D geometric constraints, and the master registry of table family
specifications for financial statements, regulatory schedules, and cover layouts.

## Purpose

Declares what each table family *looks like* — its vocabulary evidence, its geometric
bounds, its repair policy, and its scope — and nothing about how a candidate table is
scored against those declarations. That scoring is `engine/tables/taxonomy/classifier.py`.

## Contracts

- **Immutability**: Spec, match, classification, and evidence types are frozen slotted dataclasses; scope and repair-policy types are string enums.
- **Exclusion terms are advisory**: Orthogonality is best-effort; read the owning module's pack rather than assuming families are mutually exclusive.
- **One ordering source**: A family becomes real when listed in `FAMILY_SPECS`; the classifier iterates the registry rather than a second list.

## Deliberate gaps

- **No classification probe**: Nothing exposes a command to report how a candidate table scores; call the engine classifier in-process.
- **`FAMILY_SPECS` is a mutable dict**: Treat the registry as read-only; specs are frozen but callers can add or remove families.
