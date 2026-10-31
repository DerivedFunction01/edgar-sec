# `edgar_sec/domain/document` — document path facts and block contracts

## Purpose

This package owns path-based document route and suffix facts, plus immutable
normalized-document block records. It contains no acquisition or persistence
records; pipelines own retrieval policy and storage.

## Contracts

- **Path-only routing**: `document_route()` classifies published paths, while
  `content_route()` classifies already-acquired SGML filenames without directory
  semantics.
- **Exact placeholder names**: The four path names are facts; form/date eligibility
  and retrieval remain pipeline policy.
- **No content inspection**: Route and path-fact helpers do not inspect payload bytes.
- **Ordered block stream**: `BlockStream` preserves the sequence of normalized blocks.

## Deliberate gaps

- **No acquisition or persistence model**: Target selection and artifact schemas
  belong to their owning pipelines.
- **No form-aware route inference**: Route classification does not inspect filing
  metadata or validate payload contents.
