# mechanics

## Purpose

The source-mechanics scanners: the rules about how source text is
constructed. `artifact_paths` and `sec_surface` keep artifact paths and
SEC URL surfaces registered with their owning registries, `json_io`
confines JSON serialization to the shared helpers, `whole_file_read`
bans whole-file reads where streaming is the contract,
`sql_interpolation` bans interpolated SQL outside the compiler paths,
`string_lookup` bans semantic string searching on structured names, and
`regex_alternations`, `uncompiled_regex`, and `sha256_validation` keep
regex construction and digest validation in their compiled, homed
forms.

## Contracts

- **Construction goes through the homed helper**: each rule names the
  helper or registry that owns the construction; a private second form
  is a finding even when it behaves the same.
- **Registration is central**: every module here registers only through
  `ALL_SCANNERS` in the parent package's `__init__.py`.
- **Support flows from the parent root**: modules import `Scanner`,
  discovery, and the text-rule helpers from the parent package's root
  modules (`base`, `files`, `lines`), never from a sibling subpackage.

## Deliberate gaps

- **Line- and AST-shaped reach**: a construction assembled across lines
  or built dynamically can evade the text-shaped members of this family,
  as the parent package's README records for the scanner set as a whole.
