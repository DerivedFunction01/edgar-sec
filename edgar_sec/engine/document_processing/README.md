# document_processing — Layer 3

## Purpose

Resolves acquisition operations against family policy, document path facts, and registered runtime handlers, then executes those handlers over explicitly supplied source bytes.

## Contracts

- **One operation resolver**: Planning pins and Engine execution use the same family, capability, and handler resolution rules.
- **Route source is explicit**: `DocumentPathFacts` distinguish published archive paths from SGML child filenames; child route classification uses content suffixes, not path separators.
- **PDF rendering is suffix-gated**: The binary route renders only the PDF suffix class; other binary suffixes stay refused, and a PDF with no text layer yields an explicitly empty render, never a fabricated one.
- **No acquisition orchestration**: This package does not select sources, persist operation pins, or write pipeline artifacts.

## Deliberate gaps

- **Limited built-in transforms**: The default registry supports raw identity, text normalization, and PDF text extraction; XML conversion requires a registered capability and handler. Render-to-text of a flat XML primary for a family with no profile is not applicable, not unsupported: XML is data, and no text render is attempted.
