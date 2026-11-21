# runtime

## Purpose

The runtime-discipline scanners: the rules about how code touches its
execution environment. `environment` confines environment access to the
one settings seam, `resources` bans hardcoded worker and memory limits
outside the derived budget, `batch_defaults` bans hardcoded batch sizes,
`clean_exit` confines process exits to entry points, and `secrets` bans
credential-shaped literals in tracked source.

## Contracts

- **One seam per resource**: environment, budgets, and exits each have a
  single owning module elsewhere in foundation; these scanners flag any
  second path to the same resource.
- **Registration is central**: every module here registers only through
  `ALL_SCANNERS` in the parent package's `__init__.py`.
- **Support flows from the parent root**: modules import `Scanner`,
  discovery, and the text-rule helpers from the parent package's root
  modules (`base`, `files`, `lines`), never from a sibling subpackage.

## Deliberate gaps

- **Signature-based detection**: `secrets` reads a narrow signature set;
  a credential in an unscanned shape or outside the scanned trees is
  invisible, as the parent package's README records.
