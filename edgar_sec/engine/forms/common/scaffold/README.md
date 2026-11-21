# `edgar_sec/engine/forms/common/scaffold` — form-family scaffolding

Submission header parsing and shared scaffolding for the form-family analyzers.

## Purpose

Owns the frame family packages stand on: shared header parsing for
edgarSubmission-rooted SEC XML forms (`edgar_submission`), and the shared
scaffolding for the form-family review analyzers and renderers
(`family_scaffold`).

## Contracts

- **Frame, not content**: Scaffolding wires family analyzers and renderers
  together; field semantics stay in `fields/` and the family packages.

## Deliberate gaps

- **No family logic**: A behavior specific to one form family lives in that
  family's package, never here.
