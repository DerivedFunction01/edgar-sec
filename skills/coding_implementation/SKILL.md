# Coding Implementation

## Work the task, not the conversation

- Accomplish the task iteratively, breaking it into clear steps and working through them methodically.

- Ask the user a question only when an actual answer is needed to proceed correctly. Use the tools and the codebase to resolve everything else.

- Do not start messages with Great, Certainly, Okay or Sure. Write direct, technical messages that state what was done, what was found and what remains.

- End the final result as a final statement. Do not end with a question, an offer of further help or a request to continue the conversation.

## Fit the codebase

- Read the code around a change before making it, including the callers, the tests and the repo rules that govern the area, such as an AGENTS.md.

- Follow the project coding standards, naming, layering and design patterns already in use. Match the surrounding code rather than introducing a new style.

- Check that each change is compatible with the existing codebase, its supported versions and its public interfaces before relying on it.

- Keep each change scoped to the task. Flag unrelated problems you find in the final report instead of fixing them silently.

## Implement and verify

- Complete one step successfully before starting a batch of similar changes, then continue only when the result supports the rest.

- Run the tests that cover the changed area, using the exact test paths or commands the repo prescribes, and run the repo's gate change-aware, scoped to the delta's affected modules — including when the change crosses layers. A full check (`check.py --all` or an equivalent whole-suite run) runs only when the user stated it for that work, never as a default.

- Read failures before retrying. Fix the cause the output supports and check the state a failed run left behind before repeating an action that may have taken effect.

- Verify the finished result against the original request, including edge cases, error paths and any formatting, lint or type checks the repo runs.

## Track the work where the viewer can see it

- In a repo the workbench viewer serves (it carries a `workbench.yaml`), work lives in a bundle under `.plans/<date>-<slug>/` and progress is tracked in the bundle's todo files — one file per todo under the bundle's `todos/`, created and moved only through the harness (`wb bundle new`, `wb todo new`, `wb todo set`), so the viewer's Todos and Board read them live. File todos are the model; the registry DB's todo table is superseded and takes no new work.
- Create the todos before starting, one per plan step or work item. Every todo states its completion-time estimate (inherited from its plan step's `est:` where it has one), priced under the supervision rules' Estimates passage — the discipline is mode-independent law there, and this skill cites it rather than restating it: the scale, the category register, the long-duration classes and their boundaries, per-item pricing against an inventory, and wall-clock under a fan-out all read from that passage. A todo that passes its estimate without completing is overdue and is actuated upon — re-estimated with its reason stated, staffed, or escalated — never merely re-reported. Move each todo's status at the transition (`todo` → `doing` → `done` / `blocked`), never in a batch at the end. A blocked item is marked `blocked` with the reason in its body the moment it blocks; a silent stall is a process violation.
- Adopting a plan is a defined act, not a reading of it. Validate first: `wb plan-check` must pass — a plan with prose-only steps, undeclared prerequisites, dangling or cross-goal edges, or a cycle is not adopted, and no todos are minted from it. Mint the todos from the steps' blocks, each carrying its block's `requires`; the minting runs the adoption evaluation, which stamps armed every todo whose prerequisites already read done (the plan's initial frontier, including its zero-prerequisite steps), so parallel work is exposed at adoption rather than discovered later. Execute the plan's stated fan-out as stated — the lane split is data in the blocks, not something the implementer re-derives. From there the record maintains the frontier: a move to `done` re-evaluates the goal's graph in the same write and stamps armed the dependents it completes, and `wb due` is the one read of what stands armed and unstaffed.
- Every plan implementation carries a status-update interval from the start. In a workbench-served repo this is automatic: moving a todo to `doing` with its progress schedule armed makes the harness write the matching scheduler progress-check entry, and the terminal move deletes it — check the write's `progress_entry` outcome (or reconcile with `wb progress --sync-entries`) instead of building a second monitor. Where the harness does not cover the work, or the sync failed, set an equivalent interval before work proceeds — a scheduler-registry progress entry or a goal-owned schedule at a 15- or 30-minute cadence (15m for delegated, detached, or fast-moving work; 30m otherwise — never longer, since an uncaught error must surface within one missed interval, not hours) — and remove it when the work completes or blocks. The interval checks the work and surfaces only milestones, stalls, blockers and completion; it never expands scope and never blind-retries irreversible or login-limited actions.
- Record checkpoint deploys in the relevant todo (what shipped, when), so the board shows what is live, not just what is coded. Chat is not the progress record — the todo files are.

## Report the result

- When the work implements a plan, close the plan out in the same pass that records the landing: set its `Status:` to `complete` (or `superseded`) and move the file to the repo's `.plans/finished/`. Never leave a landed plan active — the workbench viewer lists it as live work and flags the disagreement as an error.
- Remaining work never holds a landed plan open. Work beyond the plan's scope is written up as a followup plan (a new plan or bundle with its own todo files) carrying only the remainder, and the older plan is archived in the same pass with its `Status:` line naming the followup as the carrier. A completed plan is never edited again; post-completion life (verification, deployment) rides the bundle's todo files.
- Report the files changed, what each change does and the tests or checks run with their outcomes.

- State any step that was skipped, blocked or left unverified, with the reason, rather than implying full completion.

## External services

- External services (such as GitHub) are reached through your harness's connectors and integrations, in whatever form that harness exposes them.
