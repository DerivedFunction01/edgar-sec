# structure

## Purpose

The structure scanners: the rules about the tree's own shape.
`layers` enforces the acyclic downward-only layer architecture,
`legacy_shims` bans backward-compatibility shims and barrel re-exports,
`length` and `prose_length` cap file size and prose runs,
`helper_duplicates` bans duplicated helper bodies outside their one
home, and `test_tree_paths` keeps the test tree mirroring the source
tree.

## Contracts

- **The gate judges its own tree**: these scanners run over the scanners
  package itself with no exemption for their own modules; a grouping or
  rename that breaks a path rule fails here first.
- **Registration is central**: every module here registers only through
  `ALL_SCANNERS` in the parent package's `__init__.py`.
- **Support flows from the parent root**: modules import `Scanner`,
  discovery, and the text-rule helpers from the parent package's root
  modules (`base`, `files`, `lines`), never from a sibling subpackage.

## Deliberate gaps

- **No intra-package cycle detection**: `layers` ranks whole layers;
  cycles inside one package are caught by review, not by this family.
