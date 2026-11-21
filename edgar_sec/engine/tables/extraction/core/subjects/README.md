# `edgar_sec.engine.tables.extraction.core.subjects` — Subjects

The subject side of the extraction core: which family a table is about —
the family profile registry, signature profiles, the measured
subject-evidence map, the subject vocabulary, and classification.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Family classification | [classification.py](classification.py) |
| Family profile registry | [profiles.py](profiles.py) |
| Signature profiles | [signature_profiles.py](signature_profiles.py) |
| Measured subject-evidence map | [subject_evidence.py](subject_evidence.py) |
| Subject vocabulary | [subject_vocabulary.py](subject_vocabulary.py) |

## Contracts

- **Family profiles live once, as data, in the profile registry**
  (`profiles`): a family outside the registry does not compete — absence
  is the whole mechanism, never a code branch.
- **The subject-evidence map is data, not code**: `subject_evidence`
  loads the versioned flat map beside it (`subject_evidence_map.json`);
  it carries free-text evidence only.

## Deliberate gaps

- No text or period mechanics live here; those are owned by the sibling
  `text` group and the core root.
