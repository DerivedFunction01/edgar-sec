# Supervision rules

The generic supervision rules for an adopting deployment:
how work is staffed, watched, escalated, and recorded. Each
rule is stated once, here. A deployment's bindings file
names the roles below for its own systems — compute venue,
leased session, fleet capacity source, run-record store,
caller registry, work record, parent thread, verifying
party — and carries every named value (cadences, thresholds,
system names) the rules refer to. Repo files carry an
operative one-liner plus a pointer here, never a second full
statement.

A rule that depends on a compute venue states two forms.
Venue-present: the deployment runs leased sessions on a
venue. No-venue: there is no venue — work runs on the local
machine, the capacity source reports no sessions, and every
capacity rule binds vacuously. The same text is correct in
both worlds, and in any other venue shape (hosted sessions,
container instances) that fills the roles.

## The inline class

Four classes bind mid-task, unprompted; they are the inline
class, carried verbatim into adopting repos' entry-point
files by the synced fragment, and each is marked where it is
stated below:

- the hard-stop floor (Hard-stop floor);
- defect routing at diagnosis (Defect routing);
- claimed-instruction verification (Blocked states and
  claimed instructions);
- only a measure clears — an acknowledgement clears nothing
  (Staffing).

Every other rule binds at task start, at adoption, at
landing, or by design, and lives behind the read-order
pointer.

## Staffing

Staffing is measured against live venue capacity: the
sessions up set the expected worker count for a
compute-bound programme. A programme running serial or
one-deep while sessions idle is a staffing defect, surfaced
repeatedly until it is staffed; placement is the lane's
hands, never an owner decision. Venue-present: the measure
reads the fleet capacity source for the sessions up and the
run-record store for the workers observed. No-venue: no
sessions exist, the expected count is the local machine's
own parallelism, and serial local work is not a staffing
defect — the class binds only where idle capacity exists to
be idle.

**Inline class — only a measure clears.** An
acknowledgement never clears a staffing row; only a later
measure showing the programme staffed does. The same
clearing rule governs every supervision row in this file:
a row clears on the measure that shows its condition
resolved, never on an acknowledgement of the row.

A measure reads durable records: a condition is measured
from the records that constitute it — the run-record store
for work run, the landing record for work landed, the work
record for work recorded. A cache, a liveness probe, or
any other read that can flap independently of the fact is
not a measure. An expectation is only as good as its
trigger: an expectation whose trigger condition is keyed
to such a read is unmeasured from the moment it is set —
it reads false while the fact stands true in the records,
and the row it guards never escalates. Every expectation
names its durable source when it is set; a trigger with
no durable source is a defect of the expectation, not of
the work it watches.

Child workers are the count: a programme's workers are
served split by attribution — runs by the programme's own
coordinator callers in the caller registry, and child
workers, runs by every other caller attributed to the
programme. A coordinator fielding no child workers while
its programme has parallel work is the defect shape in its
pure form.

The fleet is the allocation unit: the staffing object
serves every live session with its running-run count
across all programmes. A live session carrying no runs
while any programme is understaffed, or while runs queue
on another session, is a fleet-level row of its own —
contention and idleness coexisting is a defect, not a
wash. Compute work spreads across every live session
rather than queueing on one. No-venue: there is no fleet,
and this rule binds vacuously.

Idle with work complete is its own class: a programme
whose work record shows its referenced work done while
its work stands unlanded and nothing is in flight is
surfaced as idle-with-unlanded-work, with the minutes
since its last activity evidence.

A completed stage with no successor staffed is a staffing
defect: a programme terminal-done, or with its referenced
plan derived done, while its project holds approved
unstarted plans and it fields no workers, is surfaced
until a successor is staffed or the programme closes.

No lane is called idle from its record alone: before a
stall or staffing row reads a lane idle, the measure
cross-checks ground truth — the run-record store and the
work record's modified stamps on its referenced plans.
Work moving while the record stands frozen is a
missing-record defect of its own class, carrying the
checkpoint gap: the age of the lane's newest checkpoint
against the armed progress-checkpoint cadence (a mechanism
default; its value is owned by the bindings layer).

Actuation is part of the measure: a supervision steer that
cannot reach an agent able to act is itself a defect after
one failed cycle, never a silent loop. When the dispatch
consumer reports a delivery failure for a send addressed
to an understaffed programme's thread, the next
supervision report carries an undeliverable row for that
programme addressed to the parent thread.

Escalation is timed, to the parent: a row starts in the
lane's hands; a row still unstaffed after the escalation
interval (a mechanism default; its value is owned by the
bindings layer) escalates to the parent thread and stays
escalated until a measure shows the programme staffed.
The parent step replaces endless direct re-pings.

Replacement at the stall bound: a lane that misses two
progress-checkpoint intervals is replaced, not
re-steered. The programme's coordinator names a successor
in the same movement the second miss is measured, on the
same commission — the same work item, branch, and caller
lineage — and the takeover is recorded in the programme's
plan record; the stalled lane stands down on that
commission under the one-executor rule when the successor
claims it. Re-driving a stalled lane happens inside the
two intervals, never as a further wait past the bound. A
stall reaching a third missed interval with no successor
named is a defect row naming the coordinator's
non-response, addressed to the parent thread.

The evidence is priced: every row serves its measured
sentence — active workers, child workers, per-session run
counts where a venue exists, idle-session minutes while
any queue waits, and the checkpoint gap — and every
stall-class row carries its stall duration, measured from
when supervision first saw the row, alongside the measured
size of the work it interrupts: the jobs run in the
window, the workers fielded, and the work's own expected
duration where a plan states one (unstated serves null,
never a guess). An escalation shows when the stall exceeds
the work it interrupts.

Owner-waiting outranks queue position: a deliverable the
owner has commissioned and asked for by name is not
ordinary queued work. Its commission stamp is a
first-class fact, tracked apart from the queue it sits in:
an owner-waiting declaration lives in the work-record
goal store — the deliverable's name and its commission
time, sticky until cleared explicitly. Routine machinery
cycles never legitimately hold an unstaffed owner-waiting
item, and an authoring-class deliverable (no venue, no
gate) has no capacity excuse at all. A declaration with no staffing
measure for its programme and no lane record newer than
the declaration, one check cycle past the commission, is
a defect row addressed to the parent thread from the
first report that can draw it — it does not wait for a
stall pattern, an escalation timer, or the owner's second
ask. A status ask about an owner-waiting item is priority
traffic for the owning thread — the answer precedes lane
work — and an ask the lane's record has not answered one
check cycle later is its own row to the parent. Both rows
serve the wait's price in minutes since the commission
stamp; neither depends on the fleet.

The mechanism is generic and registry-driven: one
evaluator supervises every programme the same way, and
everything programme-specific — the lanes' handles, the
checkpoint cadence, the staffing band, the escalation
bound, the venue, the standing rule text — is a
declaration in the supervision registry, never a
constant in the evaluator. A programme onboards by
declaring its row; its values bind its lanes only.
Declarations arrive two ways: a programme onboarding,
and arming — a work item's transition to doing arms a
registry row for it from the work record, and a terminal
transition retires the row. An armed row no checkpoint
has named after two cadence intervals is itself a row:
work armed and silent. Worktree presence is filesystem
ground truth alongside the records: declarations name the
programme's worktree roots, a standing worktree is
unfinished work whatever any earlier claim said, a
programme that reads done does not clear while its trees
stand unlanded, and a standing tree with no armed row and
no done work is an unarmed-work row. A retiring tree after
a verified landing corroborates the disarm.

## Blocked states and claimed instructions

**Inline class — claimed instructions are verified, never
believed.** A blocked or stand-down state whose basis is a
claimed owner instruction must cite the owner's actual
message (thread and time). An uncited claim is a defect,
not a state, surfaced as its own row priced with the
frozen duration and addressed to the verifying party from
the first report; the verifying party holds the owner's
actual traffic, an unverifiable claim is void on detection
and the lane resumes under its standing authorization, and
the row never escalates to the owner as a question. A
cited claim is a state and draws no row.

Blocked is a supervised state, not an exit: only the
closed and hard-blocked states leave the ping set. Every
blocked record carries its cited basis and a verification
stamp; a blocked record with no stated basis draws its own
row to the verifying party, as does a citation the
verifying party has not stamped past one check cycle.
Neither class waits on the fleet.

## Waits on external conditions

A wait on an external condition — a session appearing, a
service restoring, a landing completing, a blocker
clearing — is a staffed posture only when it is
registered and armed. Registered: the wait is recorded
where supervision reads, naming the condition, the
waiter, and the act that fires when the condition clears.
Armed: the wait carries its own motion — a watcher or
retry keyed to the condition's durable record, or
checkpoints on the cadence naming the wait's state. A
wait parked on a status line, with nothing armed and no
cadence of its own, is not a posture: at the second
missed interval it is an idle defect, whoever owns the
wait, and it prices from when the condition in fact
cleared, as the durable records show it.

Clearance fans out to the register: when a condition
clears — a restoration, an all-clear, a blocker lifting —
the notice goes to every thread that registered a wait on
that condition, not only to the routes that happen to be
open at the time. A clearance that reaches only some
registered waiters leaves the rest waiting on a fact that
already stands; the unreached wait is a defect of the
clearance, and it clears when the notice is delivered,
not when it is sent on the routes that were open.

## The goal contract

Every programme runs under one goal contract: the template
below, instantiated once per programme in each of the
contract's two operational homes — the scheduler's job
definitions, as the header block of every programme-serving
job body, and the work record, on the programme's bundles
and todos. No other home carries a contract: a record that
runs nothing holds no programme's terms. The supervision
layer reads the work-record-carried contract as its
declaration source and dispatches continuation pings
against it.

The six fields:

- **Objective** — the outcome, in one or two sentences.
- **Complete when** — a verifiable condition: a landed
  SHA, a verdict record, a measured count. Never an
  impression.
- **Blocked only when** — a named hard stop, a genuine
  owner-only decision, or a verified external blocker.
  The claim carries its cited basis, with its time, and a
  verification stamp; an uncited or unverified claim is
  void — the work resumes under its standing authorization
  and the claim is surfaced as a defect. Sequencing
  choices, agent-clearable waits, and matters already
  decided are never blocked states.
- **Work record** — where progress is measured: the record
  the cadence reads.
- **Cadence** — conforming progress-checkpoints on the
  armed cadence while doing; two missed intervals is a
  stall. The cadence is a mechanism default; its value is
  owned by the bindings layer and substituted at
  instantiation.
- **Continuation** — a step landing staffs the next in the
  same movement; a turn ends only with work in flight, a
  complete report, or a blocked report satisfying the
  Blocked only when clause. An acknowledgement does not
  clear a stall; measured movement does.

Fields-only variance: exactly four things differ per
programme — the programme name, Objective, Complete when,
and Work record. Blocked only when, Cadence, and
Continuation are verbatim in every instantiation; a
handwritten variant is a defect.

Start gate: a job body or work-record item with any
contract field empty is not created, armed, or staffed.
The starting thread restates the Objective verbatim in its
first progress checkpoint.

## Defect routing

**Inline class — route at diagnosis.** A defect in one of
the deployment's shared infrastructure systems is notified
to its owning thread with a fix commission at diagnosis —
never held for a hand-over, a closeout, or a defects list,
and never fixed ad hoc in the consuming thread. A defect
post naming such a system carries its routing — which
system, which owning thread was notified, when, and the
evidence pointer — or the post is incomplete. The measure
cross-checks and surfaces a visible-but-unrouted defect as
an unrouted-defect row addressed to the diagnosing lane,
escalating to the parent thread on the timed pattern; the
row clears when the notification exists, not when it is
acknowledged. The class does not depend on the fleet. The
bindings layer names the shared systems and their owning
threads.

## Gap closure

The sweep that closes gaps is the tick itself: its
measure classes live in the workbench as their
permanent home, and the workbench is their sender.
A gap is a measured condition, never a thread's
self-report — the records that constitute it are the
work record's todo files and checkpoint stamps, the
run-record store, and the fleet capacity source
(Staffing). Only a measure clears a gap row (Staffing);
an acknowledgement clears nothing.

The classes: idle, serial, stall/seam, orphan,
unreported, terminal. Idle is armed or doing work with no
conforming checkpoint past the stall bound and no
verified blocked basis (Blocked states and claimed
instructions); serial is a programme with
parallelizable work running fewer than two active
workers while a live session sits idle (Staffing);
stall/seam is a step complete at lane level whose
successor is unstaffed, or a landed hand-back nobody
consumed (Plan shape and fan-out).

Orphan, two shapes. The derived shape: a run record
with no payload finish whose evidence is stale past
the programme's window — the launch-lost shape (a
launch that died while the runner still holds the
record) and the stuck shape (a non-terminal record
whose evidence stopped advancing). A record in
flight on fresh evidence is not an orphan; a
finished record is not one either. The
underivable shape: a terminal record whose result
was never collected. The record alone cannot tell
"nothing to pull" from "never pulled" — a job that
declares no outputs pulls nothing — so that shape
stays a coordinator act until the record carries
the job's outputs declaration, and is named as a
residual wherever the orphan class is reported,
never silently dropped.

Unreported: work landed or complete that has not
been surfaced to its waiter. The owner-waiting rows
carry it: a waiter with an unanswered ask outranks
queue position.

Terminal: a run record in a terminal shape that
its owning programme has not consumed. The shapes:
a payload finish in state failed; a record closed
into state orphaned by its terminal event (the
hours before the event are the orphan class's
ground); and a record in state complete whose
declared outputs were never recovered — a terminal
state that reads complete while the substance is
absent, and the derivable face of the orphan
residual above, since such a record carries the
outputs declaration the residual waits on. The
record is the runner's, and recording is not
consumption: the collector stamps a terminal state
within seconds, and the outcome then sits silent
unless the launching seat polls for it. Consumption
is the owning programme's own record — a todo, a
pass record, a lane or coordinator record at the
programme's declared locations — citing the run in
its terminal state. A terminal run at least one
checkpoint interval past its terminal instant (the
programme's declared cadence) with no such citation
raises the row to the owning coordinator; it
re-surfaces every run of the measure until the
citation lands, and escalates under the programme's
declared escalation bound like every other class. A
clean completed run never raises it; a non-terminal
record is the orphan class's ground, not this
one's. The tick is the class's only consumer — no
per-programme watcher and no second surfacing
surface is built for it. Attribution is by caller,
and a programme whose runs ride a caller that is
not its slug stem declares its caller stems in the
registry, so the attribution stays data, never a
measure-side special case.

The actuator ladder, in order; a message alone is
the weakest form and never counts as the act by
itself. Self-collect: for a terminal-but-uncollected
record, read the result and deliver it with its
verdict — since the underivable orphan shape is not
derived, this rung stays a coordinator act. Direct
commission: steer the owning coordinator carrying
the concrete next act, drawn from the programme's
own plan and records — the named step, its inputs,
and the output that proves it started; never a
status request. No direct-to-lane channel is
invented: lanes are ephemeral and no registry route
names them, so the direct-lane rung routes via the
coordinator. Successor staffing: when a step's
landing is verified in the record, the successor
step is staffed in the same movement — the seam
never waits for a coordinator's next movement.
Verify the act: every actuation records an
expectation — the specific ground-truth change that
must appear by the next run (a new run record, a
moved checkpoint stamp, a worker count up, a
hand-back consumed). The next run checks it; an
unmet expectation escalates the channel
(coordinator note, then defect report to the parent
thread naming the non-response) and re-actuates in
the same run. An acknowledgement is not movement;
only the measured change closes the gap. A gap
actuates at most once per hour while unchanged,
unless its expectation failed verification — a
failed expectation always re-actuates immediately.
Utilization accounting: each run, per programme,
whether it had at least one active worker while
open work stood. The hourly roll-up reports the
fraction of the last four hours each programme
spent doing nothing while work stood open — that
number trending to zero is the sweep's success
measure. The fraction is computed at report time
from the todo files' full checkpoint history plus
the run records: the tick's state carries only the
latest checkpoint per lane, no history, so it is
not a tick-served field.

The scheduler-registry progress entries are retired
with this section: the tick's armed rows are the
check, and the workbench only deletes lingering
entries. The limits are the hard-stop floor
(Hard-stop floor): never push, never send anything
external, never approve a hard stop, never start
or kill a session.

## Plan shape and fan-out

Every plan carries its parallelization as a ruling: the
lane split over already-landed contracts, and each serial
exception with its named shared file or shared state. A
plan with no parallelization ruling is unfinished.
Adoption executes the plan's stated split and does not
re-derive one; plan numbering is not a dependency.

One executor per plan: an adopted plan names its executing
lane in its header, before its first edit — that edit is
the claim. A lane that finds a plan claimed by another
lane, or uncommitted changes on a plan's critical files,
stands down and surfaces the collision rather than
building in parallel on the same files. An open offer to
execute is completed by naming the executing lane when the
offer is taken up; an offer taken up in two places executes
on the first claim.

Prerequisites are data, not prose. Every step carries a
machine-readable block declaring the todos it mints and
the prerequisites those todos carry — todo ids anywhere
under the same goal — and its fan-out or its serial
exception. Succession is read from the declared
prerequisites, never from plan order or numbering.
Adoption validates the plan first (wb plan-check: no
prose-only steps, no undeclared prerequisites, no
dangling or cross-goal edges, no cycles) and arms the
initial frontier in the adoption act: every todo whose
prerequisites already read satisfied is stamped armed,
so the full parallel start is exposed at adoption, not
discovered as work lands. A todo's move to done
re-evaluates the goal's graph in the same act and arms
what it completes. What stands armed and unstaffed is
read from the one evaluator (wb due), never re-derived
from plan prose by a watcher.

Serial-plan detection at adoption: fan-out is measured
when a plan is adopted, not when the owner audits it. An
adopted plan whose remaining steps are contract-
independent and which fields fewer lanes than it has
independent steps is an understaffing row at adoption
time, escalating on the timed pattern. Lanes are counted
from the live statuses sharing the plan reference; the
step counts are declared on the status references (steps
open, steps independent), and a plan with no declaration
draws no row rather than a guessed one.

## Landing and records

Landing moves the record: whoever lands work that
completes another plan's step updates that plan's record
in the same turn, or notifies its owning thread in the
same turn — a record lagging its landing is a defect of
the landing, not of the record-keeper. A gate-green,
self-contained delta lands incrementally as soon as it is
green; holding green work for a whole-branch landing needs
a named shared-state reason, stated where the hold is
recorded.

Landing order between parallel streams is agent-clearable:
when streams serialize on a measured overlap, the owning
threads choose the order — gate-complete first, ties by
rebase and re-gate cost — and execute it. An ordering
choice differs only in sequence, not scope or outcome, and
is never escalated as an owner blocker; only scope,
outcome, and the hard-stop classes go to the owner.

## Gates

A gate scopes to the change: a lane's gate runs the tests
for its delta's affected modules — the gate tool's
change-aware selection, widened to every surface sharing
a changed contract — and never the full suite as a
requirement. Per-lane full gates are the slowness this
abolishes. Lanes fan in as union trees, and where a full
run is owed it happens once, on the union tree.

Gate work shards across the available parallel capacity:
independent gates run concurrently on separate venues,
and within a gate the parts that can run in parallel do —
across venues first, workers second. Serial is allowed
only for a named, recorded shared-state dependency.
No-venue: the capacity is the local machine's own
parallelism, and the same scoping binds.

Union once, gate once: when several deltas are
landing-bound and their pre-states are measured — each
delta's tree hash-verified into the union, disjoint files
blob-identical — form the one union and run the one gate
on it; gating each delta separately and then re-running
the overlapping tests on the union is double work.
Formation hash-verification stays — it is what makes the
pre-state known; per-delta gates remain only for deltas
whose pre-state is not yet known.

A full run is a proof instrument, not a landing gate:
where one is owed it runs last, and even it may skip
areas the delta does not touch. A proof whose subject is
a tree-wide condition keeps its full run over its
subject's own surfaces — the subject's surfaces always
run. A full run runs only on the owner's explicit
consent, and under exactly one conditional: the proof's
subject is itself a tree-wide condition. Every other
gate is change-aware scoped to the delta's affected
modules, whatever the delta's size or the tree's status;
a gate template whose default is a full run is a defect
of the template, not of the lane that fired it.

Landings gate on compilation: a landing proceeds on the
tree building; test and end-to-end runs execute in
parallel, report after, and their defects land as
follow-up fixes. Waiting on a test run to land is a
scheduling defect.

Markdown carries no gate beyond the scanners that read
it: a markdown step lands on scanner-clean — or on
nothing, where no scanner reads the file — and never
queues behind test runs or gate draws.

## Venue use

Sessions are shared computers, not queues: another
programme holding a session is never a reason for a gate
to wait. Draws co-run on live sessions, sized down to
measured headroom (cores, memory); ports are
single-occupancy and stay distinct per lane; a measurably
starved draw is reported as a sizing fact, never silently
re-queued. No-venue: there are no shared sessions and no
draws; work runs locally and this rule binds vacuously.

Work on a reduced-capability venue tier states its
justification where it reports status — unprompted, at the
point of choice; when a full-capability session is up, the
justification names why it was not used. No justification
that survives stating means the work moves to the
full-capability tier instead. No-venue: the local machine
offers no tier choice, and nothing is owed.

## Status vocabulary

A status report is grouped, never a bare code: it carries
exactly the groups its state selects, one line per group,
a group with nothing to report omitted and never filled
with a placeholder. The done group names the work items
flipped since the last report wherever work items exist;
summary-form done is legitimate only at the two closing
states. Work running past an hour while its thread stays
active states itself under stalling — long-running is
self-stated at the hour, not discovered after the fact.

The per-state forms:

- Working and Continue carry the full set: done; ongoing;
  computed locally while a full-capacity venue is up;
  serial work that should be parallel; stalling, and why,
  and what would speed it up; duplicate-intent
  consolidation; docs state.
- Blocked-owner and Blocked-hard carry done-so-far plus
  the blocker: the blocked item, why, the exact clearing
  act, and whose it is.
- Review carries done with its gate evidence, docs state,
  and what awaits the decision.
- Done carries done, docs state, and the tail — one line
  per item with its owner: self (closeout the thread
  clears itself) or owner-decision (offered follow-ups
  awaiting accept, reject, or modify).
- Closed carries done as one summary line plus docs state.
- Parked carries done-so-far, why parked, and what resumes
  it.

The thread states are eight. Working: a work item is in
progress. Done: all work items done, with closeout or a
tail remaining. Closed: closeout landed and the tail
empty — done answers the work question, closed the
supervision question, and a closed report carrying a tail
item is a contradiction. Parked: deliberately paused by
instruction; it never reads as stalling. Blocked-owner:
the critical path sits in blocked work only the owner can
clear. Blocked-hard: the critical path sits in blocked
work a hard stop clears. Review: finished work presented
for accept, reject, or modify. Continue: agent-clearable
work remains and proceeds without a go.

The item kinds are three. A defect is a diagnosed defect
in built work, implemented without approval once
diagnosed. A follow-up is a post-plan improvement — held
at the owner's tap, built in a worktree — or a defect-fix
suggestion, which merges on a green gate. A question is a
decision handed to the owner.

A signal matches exactly or not at all; absence of a
signal never reads as completion; an unrecognized status
escalates to judgment rather than being guessed. A thread
with work outstanding and no signal on record gets a
status request, and repeats require new knowledge, never
just elapsed time. An offer exists only as a posted item:
a follow-up, improvement, or consolidation proposed in
prose alone does not exist, and a prose-only offer is a
reporting defect.

## Retiring the status-code transport

No thread posts an attention status code, and no thread
is asked for one either: the transport is removed, not
shimmed — the command-line verb, the client call, the
server route, and the ingest writer are deleted, and a
call to any of them is an error, never a silent no-op.
Staleness is computed, never requested: every
programme's state measures from records alone.

The record sources, one per question. Topics come from
the registry's programme declarations plus the armed
work-record entries — a topic with no armed entries has
no live work. Liveness and completion come from todo
statuses, checkpoint stamps, and worktree presence: a
standing worktree is unfinished work whatever any
earlier claim said, and a programme is complete only
when its armed entries are terminal and no worktree
stands unlanded. Blocked claims come from blocked
todos: the todo's status is `blocked`, its basis is in
its body, and its citation is a body line naming the
owner's message thread and the time — a claim without
one is unverified, never a state. Owner-waiting
declarations come from the work-record goal store,
where they already stand as a sticky field. Armed work
with no checkpoint is unsupervised work, measured from
the checkpoint stamps, not from any post naming the
todo. The serial-plan row is retired: the plan-frontier
shortfall row subsumes it, measuring declared fan-out
against the actual in-flight set.

The surfaces that read records alone once the transport
is retired are the sends ledger — the steers and
escalations the tick sends — and the staffing rows the
measure serves. No live surface reads a status code.

Named remainder, not silently left: the digest's
historical rendering of posted records and the waits
engine's terminal-code facts still read the store's
existing status records — no new posts arrive — and
the goal record's own post store is an adjacent
surface with its own writer rules. The status
vocabulary above remains the language of those
historical records and the waits engine; it no longer
describes anything a thread posts.

## Surface structure

Items and elements are separated by structure, never by
characters and never by where a line happens to wrap.
A surface never joins items into one dot-separated
string: each item gets its own row, or the surface
compacts to a summary — a count, tap to expand. A space
is not a valid separator: items are separated by rows
and layout, never by spaces inside a string, and
wrapping behaviour is consistent across surfaces of a
kind. A summary never repeats its title: title and
summary are separate elements on a row, and the summary
carries what the title does not say.

## Hard-stop floor

**Inline class — the floor is not declarable.** Permission
cards, scope expansions, logins, external sends,
purchases, sensitive form submits, real-calendar writes,
and schedule changes never auto-apply in any presence. No
declarable rule may name one — such a rule is refused at
posting; their only rule-side form is a shadow proposal;
and approve-once, deny, and push are never rule-eligible.

A permission card is a registered hard-stop wait class,
and a lane a card blocks posts its own wait for it. A card
that blocks no watching lane has no self-poster under this
shape — a named, open residue, not a silent gap.

## Auto-rules

**Shadow-first discipline.** Any action may be promoted to
an automatic rule by a deliberate promotion act, and every
such promotion lands in shadow — evaluated and reported,
never fired — the one exception being the approval of a
wait, which lands active. The seed patterns below start in
shadow together.

The seed patterns (the evaluated rule records themselves
stay engine data):

- A defect item clears when its subject reaches a terminal
  state.
- A stale record draws a record-gap row.
- A performance clearance is served as for-information,
  not as a decision.
- Work that reads done while its trees stand unlanded is
  reported against the tree, not taken.
- Work done on a user-interface-surface handler
  dispatches a critic commission; the surface mark is a
  flag on the handler registration.
- A completion proposes a consolidation pass; the trigger
  reads the work record's derivation at evaluation time.

## Code and documentation patterns

No backward-compatibility shims and no barrel re-exports:
never create alias modules or forwarding functions when
moving code — update all call sites instead. Package init
files carry no re-exports (docstrings, version, and true
dynamic registries excepted); consumers import from the
leaf module.

Resource budgets are derived, never hardcoded: worker
counts and memory limits are sized from measured
availability on the machine the work runs on — host and
container-limit signals, with a safety fraction — by a
resource-derivation function, and hardcoded thread or
memory limits in library and pipeline code are
scanner-blocked. The derivation function's name is the
adopting repo's binding.

Settings are a modular registry under one environment
seam: providers register per domain or phase — no
monolithic configuration class; dotted paths map
deterministically to environment names; direct environment
access outside the seam module is scanner-banned;
secret-marked settings are stripped before anything is
persisted; precedence runs command-line over environment,
and stored configuration over defaults. The seam module
and provider paths are the adopting repo's binding.

One owner per recognizer or helper: a shared recognizer,
pattern, helper, or date/time derivation has exactly one
homed module per intent. A consumer that needs more of it
extends the home; it never defines a local copy, however
small the difference looks. This extends the one-source
rule beyond constants: the governed thing is the behavior,
not only the value. Enforcement is shape-based at the
gate — the scanner knows the family-to-home map and flags
the local definition's shape wherever it appears — and
duplication is measured per family, with the census of
private copies trending to zero.

Every package README carries a Purpose section, a
Contracts list of bolded invariants, and a Deliberate gaps
list — neither as a table. It states intent rather than
specifics: counts, versions, and defaults live in the code
that owns them. It cites only paths that exist in the
repository, and it documents verified behavior — planned
work is recorded as a gap, never described as working. If
a section can be autogenerated, it is dropped.

Comments and docstrings default to none: prose earns its
place only by stating what the code cannot. Hard caps
apply per prose kind (module, function, comment block;
tighter for tests), exceedable only for a precondition the
type system cannot express; the caps' values are owned by
the bindings layer, and enforcement is by the prose-length
scanner. Prose documents intent, not execution, and serves
six justifying categories: a non-obvious invariant, a
refusal semantic, an ordering or atomicity constraint, a
caller obligation, a safety or integrity rule, an
inexpressible precondition. Never narration, measured
figures, project vocabulary, or a restated rule. Changing
code does not license growing its prose.

Fixture discipline: default unit tests are offline,
deterministic, and fast. There are no nondeterministic
tests: a test that flakes is changed or dropped, never
quarantined, never skipped into silence, and never
retried into green. Tests fake their live and timing
dependencies — no test waits on a real clock, a real
network, or a real external state — and the determinism
proof is repeated parallel runs, green every time.
Committed fixtures are sanitized,
minimal golden references. Data a production module
consumes is not a fixture and lives beside its owning
module in the package. Generated test outputs use
transient paths, never the repository tree.

Test-tree mirroring: the test tree mirrors the source tree
package for package, so a test file sits at the same
relative path as the module it covers — one test file per
source module — and shared setup lives in a conftest at
the narrowest directory that needs it.
