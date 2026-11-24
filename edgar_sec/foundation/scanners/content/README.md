# content

## Purpose

The content scanners: the rules about what living text says.
`living_dates` bans date forms in living documents and in code
comments and docstrings, so a living surface states the present
truth and a dated record lives in the archives, not in prose.

## Contracts

- **Registration is central**: every module here registers only through
  `ALL_SCANNERS` in the parent package's `__init__.py`.
- **Support flows from the parent root**: modules import `Scanner`,
  discovery, and the text-rule helpers from the parent package's root
  modules (`base`, `files`, `lines`), never from a sibling subpackage.
- **Dates as data are not findings**: string literals, fixtures,
  specimen corpora, and code inside a document pass; only doc lines,
  comments, docstrings, and config-file comments are surfaces.

## Deliberate gaps

- **Specimen corpora are out of the doc population**: markdown under
  `uploads/` and `tests/fixtures/` is quoted source material, so its
  printed dates are data the scanner never reads as prose.
