# ownership

Domain layer package for Section 16 insider ownership report definitions.

## Purpose

Supplies declarative processing profiles and acquisition operation rules for SEC ownership filings (Form 4).

## Contracts

- **Supported operations**: Form 4 allows verbatim `raw` storage and `render_to_xml` transform.
- **No text rendering**: Form 4 drops `render_to_txt` to avoid lossy table flattening.

## Deliberate gaps

- **Forms 3 and 5 item taxonomies**: Item-level structures for initial statements and annual updates remain deferred.
