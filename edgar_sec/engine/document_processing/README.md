# document_processing — Layer 3

## Purpose

Resolves acquisition operations against family policy, document path facts, and registered runtime handlers, then executes those handlers over explicitly supplied source bytes.

## Contracts

- **One operation resolver**: Planning pins and Engine execution use the same family, capability, and handler resolution rules.
- **Route source is explicit**: `DocumentPathFacts` distinguish published archive paths from SGML child filenames; child route classification uses content suffixes, not path separators.
- **No acquisition orchestration**: This package does not select sources, persist operation pins, or write pipeline artifacts.

## Deliberate gaps

- **Limited built-in transforms**: The default registry supports raw identity and text normalization; XML conversion requires a registered capability and handler.
