# `edgar_sec/domain/taxonomy/tables/` — Table Family Specification Types

Pure declarative models and 2D geometric constraints: the type layer that the statement
vocabulary modules in `domain/taxonomy/statements/` build their family specifications
from.

## Purpose

Declares the specification types — vocabulary evidence, geometric bounds, repair
policy, and scope — as data. Nothing in this package assembles the per-family
specifications into a registry, and nothing scores a candidate table against them.

## Contracts

- **Immutability**: Spec, match, and evidence types are frozen slotted dataclasses; scope and repair-policy types are string enums.
- **Exclusion terms are advisory**: Orthogonality is best-effort; read the owning module's pack rather than assuming families are mutually exclusive.

## Deliberate gaps

- **No registry**: Family specifications are declared in their owning statement modules and consumed directly; no module collects them into a master list.
