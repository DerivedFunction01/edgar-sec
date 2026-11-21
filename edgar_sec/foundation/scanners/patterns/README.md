# patterns

## Purpose

The recognizer-pattern scanners: each one bans a private pattern core — a
date, money, page, period, identifier, or reference-cell recognizer, or a
bare pattern fragment — outside the one home the vocabulary owns, so a
recognizer family has exactly one definition the rest of the tree imports.
`pattern_registry` is the family's registry half: it carries the homed
pattern table the shape rules read.

## Contracts

- **One home per recognizer**: a pattern core found outside its registered
  home is a finding; sanctioned divergences are named in the owning
  scanner, never in a side list.
- **Registration is central**: every module here registers only through
  `ALL_SCANNERS` in the parent package's `__init__.py`; no module here is
  imported directly by a consumer outside the registry and its tests.
- **Support flows from the parent root**: modules import `Scanner`,
  discovery, and the text-rule helpers from the parent package's root
  modules (`base`, `files`, `lines`), never from a sibling subpackage.

## Deliberate gaps

- **Shape, not semantics**: the scanners match pattern shapes in source
  text; a recognizer assembled dynamically at runtime is out of reach.
