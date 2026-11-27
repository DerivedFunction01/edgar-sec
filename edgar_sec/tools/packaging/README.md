# packaging

Layer 6. Installed-form verification for the built package.

## Purpose

Prove the packaged form works the way a user receives it: builds, installs
into clean environments, and the installed data and command surface behave
from an unrelated working directory.

## Contracts

- **Three legs, honestly labelled**: the wheel leg validates the built wheel
  of the current tree; the local-directory leg validates the working tree
  itself, uncommitted changes included; the `git+file://` leg is a
  clone-mechanism proof against committed state only.
- **Opt-in only**: the battery builds and installs, so the default gate never
  runs it; invoke it directly or via `check.py --package`.
- **Taxonomy archive is seeded, not shipped**: the archive parquet slices
  are a generated class written by `tools/xbrl_discovery/build_taxonomy_archive.py`
  (and seeded by `tests/conftest.py` in a fresh clone), never wheel data.
  The probes assert the shipped taxonomy JSON tree and that the archive
  resolver answers; a bare wheel carrying no archive is a passing state.
- **The battery proves the finalized surface only**: review-plane data
  (cohort registries, review expectation JSONs) is wheel-excluded and no
  probe loads it; the import sweep still imports every shipped module,
  whose expectation loaders read their data lazily on first use.
- **Scratch lives outside the repo** and is removed after the run unless
  `--keep` is passed; the run record lands in `.artifacts/run-logs/`.

## Deliberate gaps

- **No publish step**: building release artifacts for distribution is a
  separate, owner-gated act; the battery only verifies installability.
