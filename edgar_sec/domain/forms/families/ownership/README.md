# ownership

Domain layer package for Section 16 insider ownership report definitions.

## Purpose

Supplies declarative processing profiles and acquisition operation rules for SEC Forms 3, 4, and 5.

## Contracts

- **Supported operations**: Forms 3, 4, and 5 allow verbatim `raw` storage and `render_to_xml` transform.
- **No text rendering**: Ownership filings drop `render_to_txt` to avoid lossy table flattening.
- **Boilerplate is scoped**: Shared phrase rules identify ownership prose terms; candidate extraction retains source text and decides whether to exclude a match.

## Deliberate gaps

- **No item taxonomies in this family**: Item-level structures for Forms 3, 4, and 5 remain deferred; the package declares codes and the XML schema spec only.
