# exhibit.packs.tier1

Tier 1 exhibit pack definitions for SEC Item 601 and Form 20-F classification.

## Purpose

Hosts the tier 1 `ExhibitPack` contracts: the exhibit definitions the tiered
evaluation reaches for first. Each module exports one pack's anchors, secondary
tokens, and veto signals as plain string tuples.

## Contracts

- **Declarative only**: Packs contain string metadata; zero regex compilation or I/O.
- **Tier fidelity**: Every pack here declares `tier="tier1"`; a pack whose tier
  changes moves to the matching tier package in the same act.

## Deliberate gaps

- **No registry wiring**: Pack resolution lives in `exhibits/registry.py`, which
  imports each tier package directly.
