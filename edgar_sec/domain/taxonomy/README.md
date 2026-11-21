# `edgar_sec/domain/taxonomy/` — Statutory name vocabulary

Shared vocabulary and normalizers for jurisdiction, legal-form, company-name, and filing
taxonomy data.

## Purpose

Provides the shared vocabulary consumed by domain and engine normalization. Financial
statement and table taxonomies are documented in their subpackage READMEs.

## Contracts

- **Immutability**: Vocabulary tables are immutable shared inputs; one caller cannot change what another sees.
- **Normalization**: Jurisdiction cleanup strips recognized suffixes; legal forms and company-name tokens are normalized against vocabularies.
- **Canonical codes**: State codes and names have one canonical vocabulary shared with cover vocabulary.
- **Deterministic expansion**: Ambiguous abbreviations expand only under neighbor constraints.
- **Deterministic family resolution**: A fixed seed breaks ties when choosing a family representative.

## Deliberate gaps

- **Jurisdiction cleanup is US-only**: The vocabulary covers US states and territories; foreign jurisdiction suffixes are not stripped.
