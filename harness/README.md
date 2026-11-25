# Harness bindings

Everything agent-harness-specific in this repo lives in this
folder, so the spec, the docs, and the skills stay generic:
any coding agent — Muse, Cursor, Claude Code, Codex, or
another harness — reads the same spec, docs, and `SKILL.md`
files and substitutes its own tools for the generic
capabilities those files name (read a file, write a file,
edit a file, run a shell command, present a file, offer
tappable next actions). No generic file names one harness's
tools or assumes one harness as the default agent.

## Contents

- `connector-setup.md` — consuming the harness connector:
  the tool contract, caller registration, and the token
  discipline. The connector's CLI client is `connector/`.
- `connectors.md` — the connector and skill-discovery
  bindings the coding skills point at: which connectors a
  Muse-side agent finds, and how it finds more.

## The Muse binding

Where a generic file names a capability, a Muse agent uses:

| Generic capability | Muse tool |
| --- | --- |
| Read a file | `muse.read` |
| Write a new file | `muse.write` |
| Edit a file in place | `muse.edit` |
| Run a shell command | `muse.exec` |
| Present a file in chat | an attachment line: `![<name>](sandbox://workspace/<path>)` |
| Offer tappable next actions | `muse.create_options` |
| Find a connector | `muse.connector_search` |
| Find a skill | `muse.skill_search` |

Another harness's binding is a table of the same shape,
kept with that harness's own configuration, not in this
repo's generic files.
