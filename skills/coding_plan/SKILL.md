# Coding Plan

## Stay read-only on the codebase — one exception: the plan file

- Treat every task under this skill as read-only planning. Explore and design only. Never change the code being planned.
- The single permitted write is the plan file itself, under `.plans/` in the target repo (see "Save the plan to `.plans/`" below): creating the `.plans/` and `.plans/finished/` directories, writing or revising the plan file there with your file-write and file-edit tools, and moving a finished plan file into `.plans/finished/`.
- Do not create any other new files with your file-write tool, `touch` or any other method.
- Do not modify existing code or config files with your file-edit tool or any other method. Revising the plan file in `.plans/` is the only edit allowed.
- Do not delete files. Do not move or copy any file other than a plan file moving from `.plans/` to `.plans/finished/`.
- Do not create temporary files anywhere, including under /tmp.
- Do not use redirect operators or heredocs to write to files.
- Do not run any command that changes system state, including `git add`, `git commit`, package installs and code generators. `mkdir -p` for `.plans/` / `.plans/finished/` and `mv` of a plan file into `.plans/finished/` are the only state-changing commands allowed, and only for those paths.
- Use your shell tool otherwise only for read-only operations such as `ls`, `find`, `grep`, `cat`, `head`, `tail`, `git status`, `git log` and `git diff`.
- Stop and state the blocker if completing the plan would require a write outside `.plans/`. Do not make the write anyway.

## Understand the requirements

- Restate the requirements, the assigned perspective and any scope gates in your own words before exploring.
- Apply the assigned perspective throughout the design, such as a layer, a subsystem, a performance concern or a migration path.
- Separate what the requirements state from what you infer while exploring. Flag each inference in the plan.

## Explore the codebase

- Read every file the user names in the request before searching more broadly.
- Find existing patterns and conventions with `find` and `grep` through your shell tool, then read the matching files with your file-read tool.
- Trace the relevant code paths end to end, from entry point through the layers the change would touch.
- Identify similar existing features and use them as the reference implementation for naming, structure and testing.
- Read the repo rules that govern the area, such as an AGENTS.md, a README or a contributing guide, before proposing a structure that conflicts with them.
- Check `git status`, `git log` and `git diff` when recent or uncommitted work could change what the plan should build on.

## Design the solution

- Base the approach on the patterns found during exploration and follow them unless the plan explains why a deviation is better.
- Weigh the trade-offs of the plausible approaches and record the decision and its cost in the plan.
- Name the dependencies between steps and order the steps so each one can be built and checked on its own.
- State the plan's parallelization as part of the design: which steps run as parallel lanes, the already-landed shared contracts those lanes rely on (kit primitives, served shapes, schemas), and — for every step kept serial — the named shared file or shared state that forces it. Plan numbering is not a dependency, and a step order is not a reason.
- Anticipate the challenges, edge cases and failure modes the implementation is likely to hit and say how each one will be handled or tested.

## Detail the plan

- Write the plan in the uniform plan syntax below, so the workbench viewer can format every plan the same way. The plan file is, in this order:
  1. `# Title` — exactly one H1, the plan's name.
  2. Header fields — `Key: value` lines before the first section heading. `Status:` is required (one of `draft`, `approved`, `in progress`, `complete`, `superseded`); add `Worktree:` and `Branch:` when a build worktree exists.
  3. `## Objective` — the work stated precisely: what is being done, its scope, and the condition that ends it. State the work itself, never a restatement of the request; an agent must be able to execute from this section alone, without the conversation behind it.
  4. `## Rulings` — the decisions that bind the work, each a precise decision statement in the plan's own words: the decision, its scope, its exceptions.
  5. `## Steps` — the implementation steps (see the next bullet).
  6. `## Open questions` — present only when questions remain; never leave the section empty.
  7. `## Subplans` — present only when the plan decomposes into subplans; omit it otherwise. One bullet per subplan, each a backticked path relative to the project's `.plans/` directory. The parent alone declares its subplans: a subplan declares nothing back — no `Parent:` field, no back-reference — and the viewer groups the Plans list on this declaration alone.
  8. `## Critical files` — the closing section (see below); nothing after it in the file.
- State the parallelization in `## Rulings` as one ruling: the lane split (which steps run concurrently, and over which landed contracts) and each serial exception with its named shared file or state. A plan whose steps all run serially states the shared constraint that forces it; a plan with no parallelization ruling is unfinished.
- The ruling is the summary; each step's block (next bullet) is the machine form adoption executes, and the two must agree. A plan is unfinished until `wb plan-check` passes on it: the check refuses prose-only steps, undeclared prerequisites, dangling or cross-goal edges, cycles, and steps with no fan-out or serial exception, and prints the frontier adoption will arm.
- Write each step as a `### Step N — Title` heading whose body names the files to create or change and what changes in each one. Close every step with four labeled lines, in this order: `files:` (the paths the step touches), `verify:` (the tests to add or run, with the exact test paths or commands where the codebase makes them known — or, when a step has no meaningful verification, the literal line `verify: unverifiable — <reason>`). Gate scope is ruled: a step's `verify:` names the change-aware gate scoped to the step's affected modules (for example `check.py <paths>`), never a full check (`check.py --all` or an equivalent whole-suite run); a full check appears in a plan only when the user stated it for that work, `done when:` (the observable condition that ends the step), and `est:` (the step's completion-time estimate, stated at the scale the work runs — a code edit in minutes, many under five, and over thirty minutes unlikely for an edit, an edit step past thirty minutes being debugging, named as its class, or split; from thirty minutes the estimate's bracket carries its justification naming the long-duration class that floors it; an estimate over an hour is legitimate only for novel work, deep research, or language-model-bound work, and the step body then states why it takes that long and why the estimate should not be any lower).
- Every step carries a step block in its body: an HTML-comment sentinel opening `<!-- wb-step` with one `key=value` line per field, closing `-->`. The fields: `step=` (the step's number), `todos=` (the todo ids this step mints, `|`-separated — one for a single-lane step, several for a fan-out, so the lanes are minted together and arm together), `requires=` (the prerequisites those todos carry: todo ids anywhere under the same goal, this plan's steps or a sibling plan's; the field is always present — an empty value declares no prerequisites), `est=` (the step's completion-time estimate, the machine form of the closing `est:` line), and exactly one of `fanout=` (the step's lane split) or `serial=` (the named shared file or shared state that forces the step serial). Prerequisites are authored here as data, never left to prose: succession is read from the declared `requires`, never from plan order or numbering.
- Plans carry decisions, not transcripts. Never quote the user's messages, or any part of the conversation, into the plan: a ruling enters as a decision statement under `## Rulings`, in the plan's own words, never as a quoted block. Reserve blockquotes (`>`) for verbatim material whose exact text is load-bearing: error output, excerpts from sources, contract or API text.
- Keep the plan brief enough to follow at a glance — a verbose plan is hard to follow, and followability is the point. The objective in a few lines; each ruling one statement; each step's body only what the implementer needs to act (files, the change, the closing labels). No background narrative, no restated exploration, no justification essays: reasoning that matters compresses into the ruling or the step it affects. Detail an implementer genuinely needs lives in a linked record — link it, don't inline it.
- Lists: bullets use `-`, never `*` or `+`; numbered lists only where the order is the meaning; task lists (`- [ ]` / `- [x]`) only in `## Open questions` and explicit checklists; nesting is two spaces per level, at most two levels deep.
- Code: fenced blocks always carry a language tag (`python`, `bash`, `ts`, `sql`, `text` for plain output); every file path, command, flag, identifier and literal value in prose is inline code; commands shown are the commands to run, verbatim.
- Math: when prose would mangle a quantity — a formula, a ratio, a complexity bound — write it as LaTeX, `$...$` inline and `$$...$$` display on its own lines. No other delimiter forms.
- Keep untested claims and open questions in `## Open questions`, rather than presenting them as settled. Each question is one task-list item, with a recommendation on an indented second line (`Recommendation: ...`). When a question is answered, check the item (`- [x]`) and move the answer into `## Rulings` in the same edit, so the ruling lives in one place.
- A question that expects the **owner's ruling** (a choice between named options, an on/off state, or a short free-text answer the owner supplies) carries a **sentinel** under the item, in the plan syntax standard's resolvable-questions grammar: an HTML comment opening `<!-- wb-question` with one `key=value` line per field — `id` (a slug unique in the plan), `type` (`choice`, `toggle`, or `text`), `options` (`|`-separated, for `choice`), `labels` (the two state labels, for `toggle`), `recommended` (one of the options/labels, matching the visible `Recommendation:` line), and `answer=` left empty — closing `-->`. Yes/no rulings are `choice` with options `yes | no`; `toggle` is only for genuine on/off questions with author labels. The owner resolves sentinel questions in the workbench viewer, which checks the box and fills `answer` in the file; the transcription into `## Rulings` still happens when the plan is picked up. Questions an agent can settle later from evidence carry no sentinel.
- End the plan file with the required section below, listing three to five files, and add nothing after it **in the file**.

### Critical files
List the 3-5 files most critical for implementing this plan, one backticked repo-relative path per bullet, with an em-dash note only where the path alone does not say why it is critical:
- `path/to/file1`
- `path/to/file2`
- `path/to/file3`

## Save the plan to `.plans/`

- Write every plan to a `.plans/` folder at the root of the target repo or project being planned. If the task is not tied to a repo, use a `.plans/` folder at the workspace root. Create the folder if it does not exist.
- Name the file `YYYY-MM-DD-<short-kebab-slug>.md`, using the current date and a slug taken from the task, so plans sort chronologically and never silently overwrite an earlier plan. If that name is taken, revise that file only when the user asked to refine the same plan; otherwise add a distinguishing suffix.
- The full plan — steps, tests, open questions and the Critical files section — lives in this file. The chat response never reproduces it (see "Finish by showcasing the file" below).
- Refining a plan means editing its existing file in `.plans/` in place, then showcasing the updated file again, with the same tappable next-action options as an initial plan (see "Finish by showcasing the file" below).

## Move finished plans to `.plans/finished/`

- A plan is finished when the user says it is done, when its implementation has been completed, or when the user abandons or supersedes it.
- Closeout is part of the landing, not a later tidy: when a plan's implementation lands, the same closeout pass that records the landing sets the plan's `Status:` to `complete` (or `superseded` when another plan replaces it) and moves its file from `.plans/` to `.plans/finished/` (creating that folder if needed). A plan is not done while it sits in `.plans/` — the viewer lists it as live work, and it flags a plan whose Status and filing disagree as an error.
- Closeout never rewrites the plan beyond its Status line. A remainder that outlives the plan never holds it open: the remainder is carried by a followup plan (a new plan file, or a new bundle with its own todo files) written in the same closeout pass, the older plan is archived, and its Status line names the followup as the carrier — `superseded` when the followup replaces the plan, `complete` when the remainder is a separate unit. Post-completion life (verification, deployment, follow-ups) rides the bundle's todo files, not edits to the finished plan.
- A plan written for implementation in a viewer-served repo is written to be tracked: its steps map one-to-one onto the bundle todo files the implementation creates before starting (one todo per step), so progress is visible in the viewer as the work moves.
- Every plan's implementation carries a status-update interval. In a viewer-served repo the bundle todos' progress arming supplies it automatically (the harness creates the scheduler progress-check entry at the `doing` transition and deletes it at the terminal move), so the plan needs no separate machinery — the steps-to-todos mapping is the commitment. Where no bundle applies, name the interval in `## Rulings` (cadence and what it checks) so the implementer sets it at the start rather than improvising one; the cadence is 15 or 30 minutes, never longer.
- Leave active, in-progress and awaiting-review plans in `.plans/` itself. Do not move a plan just because the planning conversation ended.
- Before planning new work in a repo, check `.plans/` and `.plans/finished/` for an existing plan on the same topic and build on it instead of duplicating it.

## Finish by showcasing the file, not the plan text

- Do **not** paste the plan verbatim into the chat response. The plan file is the deliverable.
- **Always** showcase the plan file at the end of every planning turn — the initial plan, every refinement or revision, and any turn that edits the plan to record a decision. No exceptions, and not only when the user asks for the file. Present it as a file attachment on its own line, in your harness's file-presentation form (the bindings are in `harness/README.md`), preceded by one complete standalone sentence; otherwise give a labeled link to the file.
- Accompany the showcase with a short summary only: what the plan covers in one or two sentences, how many steps it has, the critical files by name, and any open questions that need the user's call.
- **Always** close with the next actions as tappable options (your harness's tappable-options mechanism, where it provides one; see `harness/README.md`), not just named in prose and not as an open-ended question. Offer at least: implement the plan with the `coding_implementation` skill; refine the plan further (such as for edge cases or a different perspective); and leave it in `.plans/` for review / leave as is. Add other options only when they are real choices for that plan (for example, answering a specific open question).

## External services

- Work against external services (such as GitHub, when the codebase lives there) through whatever connectors or integrations your harness provides. How a harness exposes and discovers those integrations is that harness's own affair, documented with the harness, never in this skill.
