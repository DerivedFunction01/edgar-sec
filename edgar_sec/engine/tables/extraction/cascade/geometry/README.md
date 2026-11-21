# geometry

## Purpose

The geometry-level half of the cascade: `geometry_text` builds a geometry's
text from a typed table's context; `geometry_scoring` prices every family's
signature profile over that text, folds form-test outcomes, and applies
scored vetoes; `detail_agreement` prices a detail table whose components
close to one line of a primary statement in the same filing;
`detail_signatures` matches named detail shapes a summary family never
carries, matched over stub + caption text.

## Contracts

- **Geometry text is carried by channel**: caption, lead-in, note heading,
  stubs, grid — scoring reads the channels, never a flattened blob.
- **Detail agreement is filing-level**: a breakdown is claimed by its host
  when its components close to one line of a primary statement in the same
  filing.

## Deliberate gaps

- **Claiming is not decided here**: these modules score and price; the
  claiming chain that consumes the scores is composed in the parent
  package.
