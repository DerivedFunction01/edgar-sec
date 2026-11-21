# Coding Session Compaction

## Compact to the exact structure

- Produce a structured summary so a subsequent agent turn can resume execution without loss of operational context.

- Use the exact section structure in the template below and keep every section and subsection, in that order.

- Write (none) under a heading when there are no bullets for it, rather than dropping the heading.

```
## Objective
- <immediate task, overarching goal, active staging, phasing gates and scope constraints>

## Important Details
- <guardrails, constraints, prohibitions, milestone statuses, schema versions, config flags and unresolved anomalies>

## Work State
### Completed
- <concrete changes, tests added or passed, documentation updated and checks executed>
### Active
- <tasks in flight, pending validation and immediate carryovers>
### Blocked
- <blockers, unresolved environment issues and gated dependencies>

## Next Move
1. <sequential next steps, starting with exactly what to execute first on resuming>

## Relevant Files
- <path> - <one line on why the file is relevant>
```

## Preserve what resumption depends on

- Preserve exact file paths, identifiers, schema versions and CLI commands exactly as they appear in the conversation.

- Retain all negative constraints, such as files or subsystems that must not be touched, phases that stay blocked or deferred, and test runner policies such as explicit test paths.

- Record milestone completion statuses accurately as done, partial or blocked. Never promote a proposed or attempted action to completed.

- Document observed anomalies and unresolved workspace states, such as a dirty worktree or a failing check whose cause is still unknown.

- Distinguish verified outcomes from inferences and carry inferences forward labeled as inferences.

- When the work is tracked in bundle todo files (the workbench viewer's live-work-tracking model), the Work State cites the bundle and its todo ids with their current statuses: the todo files are the live record, and the compaction points at them rather than re-deriving progress from the transcript.

## Write densely and factually

- Write terse bullets over paragraphs and cut conversational filler, praise and recaps of how the work felt.

- Summarize the reusable state, not the transcript. Leave play by play, tool call narration and superseded ideas out.

- Reconcile contradictions in favor of the latest verified state and note the correction where the older claim would otherwise mislead the next agent.

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with the harness's custom-connector setup skill, or build a custom connector.
