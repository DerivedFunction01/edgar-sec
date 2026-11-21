# exhibit.packs.tier2

Tier 2 exhibit pack definitions for SEC Item 601 and Form 20-F classification.

## Purpose

Hosts the tier 2 `ExhibitPack` contracts for tiered evaluation. Each module
exports one pack's anchors, secondary tokens, and veto signals as plain string
tuples.

## Contracts

- **Declarative only**: Packs contain string metadata; zero regex compilation or I/O.
- **Tier fidelity**: Every pack here declares `tier="tier2"`; a pack whose tier
  changes moves to the matching tier package in the same act.

## Deliberate gaps

- **No registry wiring**: Pack resolution lives in `exhibits/registry.py`, which
  imports each tier package directly.
