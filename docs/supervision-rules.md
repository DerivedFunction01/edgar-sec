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

Staffing is measured against the work: the staffable
count of a programme's work set sets the expected worker
count. Sessions are capacity only — they never set the
expectation, so the expectation never shrinks when
sessions drop. A programme running serial or one-deep
while its staffable work waits is a staffing defect,
surfaced repeatedly until it is staffed; idle sessions
alongside waiting work price the row, and placement is
the lane's hands, never an owner decision. Venue-present:
the measure reads the programme's work set for the
staffable count and the run-record store for the workers
observed; the fleet capacity source prices idle capacity
only. No-venue: the expected count is the staffable
count still, the local machine's own parallelism is the
capacity, and serial local work beyond that capacity is
not a staffing defect.

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

The staffable set is wider than the declared queue: a
programme's queue is an ordered declaration of work
items, landed markers, and gated items — an item gated
on a marker is staffable only when its marker lands —
and the staffable set carries, alongside the queue, the
work the queue does not declare: priced follow-ons,
register follow-ups, decomposition portions of queued
items, and preparation for trigger-bound items (the work
that can be done before the trigger lands). The declared
queue is a floor for the staffable count, never its
ceiling. When a measure shows fewer distinct families in
flight than the staffable count, the continuation steer
names unstaffed items from across the set as a staffing
commission, staffed concurrently — queue order is the
record's order, never a staffing order, and no item waits
for an earlier item's staffing before its own begins. The
commission clears under the clearing rule above — on a
later measure showing the families in flight — and on
nothing else. Items leave the queue by amendment to the
contract: landed work is pruned, and a marker flips on
the landing it records.

Distinct families in flight are the count: a programme's
staffing reads as the distinct work families it has in
flight, set against the staffable count — never as a run
total. The workers under the count are served split by
attribution — runs by the programme's own coordinator
callers in the caller registry, and child workers, runs
by every other caller attributed to the programme. A
coordinator fielding no child workers while its
programme has parallel work is the defect shape in its
pure form.

The count has a floor, and the floor is a number in the
standard: every programme states a numeric staffing
floor — the least count of distinct families in active
work while staffable work waits — in its governing text.
A floor that lives only in a reminder body, a cron body,
or a seat's practice is not a floor. The floor's value is
the programme's own, set at instantiation; the obligation
to state it as a number is the standard's. A measure
below the floor while staffable families wait is a
serial-staffing defect instance by definition, and the
row prices the floor, the families in flight, and the
shortfall.

The fleet is capacity, priced for idleness: the staffing
object serves every live session with its running-run
count across all programmes as a capacity read — it
prices idle capacity and contention, and it never
denominates staffing. A live session carrying no runs
while any programme is understaffed, or while runs queue
on another session, is a fleet-level row of its own —
contention and idleness coexisting is a defect, not a
wash. Compute work spreads across every live session
rather than queueing on one. One run per session while
staffable families wait is a serial-staffing defect
instance by definition: sessions filled one-deep is not
a staffed programme, whatever the run counts read. No-venue: there is no fleet, and this
rule binds vacuously.

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

Expected staffing is declared as lane records: one record
per lane, and each record is a declaration with a
lifetime. Declare: the staffing seat posts the expected
lane count and, per lane, an estimated duration and its
venue — the venue field is always present, and none is a
standing value for authoring-side lanes, which count
toward expected and actual exactly as venue lanes do. A
declaration is not its own yardstick: the declared count
is checked against the staffable count, and a declaration
below it is a staffing defect in itself, priced by the
shortfall. Ping: the declaration stays live only while the lane
pings; the ping is the lane's own checkpoint writes on
the supervision cadence, never a separate manual act, and
a missed ping raises the lane's row at once. Renew: at
the estimate's end the lane renews with a new estimate or
terminates; the record shows estimate against actual and
the renewal count. Terminate: only on an explicit,
checkable condition drawn from the queue's marker
vocabulary — never by silence, by expiry, or on the
lane's own say-so; an expired declaration with no renewal
and no termination condition met is an escalated row, not
a closed lane. A lane is not a session: its venue-bound
steps wait inside the lane's declared gap-wait state, and
a lane never ends, merges, or hands its item back for
want of a session — declared lanes exceeding the sessions
up is the healthy shape. The measure cross-checks three
signals — lane records, venue run records, and worktree
activity — and a disagreement among them is a finding.

The measured record is the next estimate's analogy base:
landing records, per-phase prices, and fire statistics
are priced into the next estimate of the same class, in
every work form. An estimate that ignores a measured
sink of its own class repeats it; the evidence register
that holds the measurements is the pattern library's
recorded form, and pricing from it is the loop that
keeps the library current.

Estimates are part of the record, carried on the
surface the work runs: every plan states the estimate
per step in the plan file; planless work carries the
estimate on its register row, the row standing as the
plan-substitute with its formation membership and the
gate it rides; every todo states its completion-time
estimate. The categorization and the wall-clock
discipline in this passage apply to the estimate on
whichever surface carries it. The discipline is
mode-independent: it governs any stated price in any
artifact or message — a plan, a todo, a register row,
an account, a census, a ruling, or a chat message. A
price does not escape the discipline by the
informality of its surface. Estimates are
stated at the scale the work runs: a code edit is
minutes, many under five, and over thirty minutes is
unlikely for an edit — an edit estimated past thirty
minutes is debugging, or the step is split. An estimate is
normally under an hour; a longer one is legitimate only
for novel work, deep research, or language-model-bound
work, and the entry states why it takes that long and
why the estimate should not be lower. A longer estimate
names the class that floors it, from the closed set of
long-duration classes: an irreducible serial dependency;
work CPU-bound at the full worker count; memory-bandwidth-
or I/O-bound work; limited compute or capacity queueing;
network-held work; coordination and fan-in, including
tail latency; hard language-model or algorithmic
complexity floors; critic and verification runs; certain
browser work; debugging; and real-time observation windows. The
discriminator is universal: the elapsed time sits at the
class's floor with its bottleneck at its measured
ceiling, and any proposed shortcut names what it
surrenders. Duration claimed for serial-by-default work,
polling intervals, re-running from zero, lanes queued
behind sessions, manufactured approvals, or transport
round-trips is a justification in no class.

A plan's duration is its wall-clock: the critical path
through its steps under their declared fan-out, never
the serial sum of its step estimates. A step under a
declared fan-out prices at its longest lane's
wall-clock, not its lanes summed. A summed serial figure
presented as a plan's size — in a headline, a ruling, or
a report — is a mispricing of the same class as an
unjustified overrun.

Bundled scope is unbundled at pricing time. A single
figure spanning design, build, verification, and
landing prices none of them: each part prices in its
own register against its own basis, and the stated
price is the parts under their declared composition —
wall-clock where they run in parallel, serial only
where the dependency is real. A bundle that cannot be
unbundled has not been priced.

Work prices by category; the category carries the
number, and a step prices by naming its category. The
fast categories are the default register for plan work.
Inventoried mechanical edit — a declaration plus a call,
a guard, a swap, over a censused surface: minutes per
item. Deterministic design and build — new code or text
whose shape follows a pattern of record, its edge cases
enumerable in advance: tens of minutes. Proof run —
dummy testing, gate and verification runs over a known
corpus: minutes, set by the corpus and the venue.
Coordination and fan-in — union formation, gate draws,
landings: minutes to tens of minutes. Generation- or
reading-bound work: its duration is computed, volume
over the served rate, never guessed. Each category's
typical duration carries its measured basis in the
estimate evidence register; a category whose duration
has no basis recorded there is unbacked and is marked
as such, never silently carried.

The slow register — the benchmark class — is one
category among them: genuinely novel research, hard
open-ended debugging, frontier problems with no known
shape. It is not the default register for plan work,
and it carries no typical duration: a price in it is
argued per step. A step enters it only with its
justification, at the boundaries below; a step priced
in the slow register without that justification is the
overestimate defect in its categorical form. Bounded
investigation — a question whose answer sits in the
codebase or its docs, its extent estimable — prices in
the fast categories; only research whose extent cannot
be bounded in advance enters the slow register.

Once a census or inventory of an edit surface exists,
its edits price per item at the minutes scale the
inventory makes possible. Pricing inventoried mechanical
edits as craft work is a mispricing: the inventory is
what the price is made from.

The slow register's boundaries: size alone
meets none of them. Novel work is work whose design has
no existing shape in the codebase to copy and whose
failure modes cannot be enumerated in advance;
deterministic design with known edge cases, a pattern
of record, or an inventory is not novel, however large.
Deep research is investigation whose extent cannot be
bounded in advance because the answer is not in the
codebase or its docs. Language-model-bound work is work
whose duration is set by generation or reading volume
at its measured rate. An over-hour claim that does not
meet its class's boundary is a mispricing, and the
entry's why-not-lower addresses the boundary, not the
size.

Migration-class work — inventoried code edits over a
known surface — fits a one-hour wall-clock cap for its
edit phase, after initial dummy testing on the known
edge cases; where the work cannot fit at
minutes-per-edit pricing, the lane split widens until
it does, lanes being capacity-bound, not seat-bound.
Residue that cannot price as an edit is named as
not-an-edit — a decision to take, a semantics
requirement discharged in the design step — never
absorbed into an edit estimate.

Proof is priced by the failure mode's direction. For a
continuously-used system whose failure modes are loud —
a refusal, never a silent wrong action — dummy testing
against the contract is the primary proof, and
exhaustive up-front discovery is over-priced: residue
surfaces on first real use and is fixed then. Static
discovery is priced only for silent-direction changes,
where behaviour alters with no loud signal at the point
of change.

Prices stated in rulings and decisions — a build price
attached to an option, a token's discharge price — obey
the same discipline as step estimates: wall-clock under
the declared split, per-item against an inventory where
one exists, and an over-hour class only at its boundary.

A price is re-derived when its basis changes.
Exploration completed, an inventory landed, a pass run,
or scope partially consumed each void the standing
price: the figure was paying for scope that no longer
stands. Repeating a price is re-deriving it — a price
carried into a later artifact or message is stated
again, and stands only if it survives re-derivation
against the current basis. A figure relayed because an
earlier surface stated it — priced-at as an inherited
label — is a defect of the same class as an unjustified
overrun.

The overestimate defect names in every mode, not only
in plan form. Wherever a price is stated, the remedy is
the same: re-price at the work's actual size, or name
the long-duration class the price rests on and the
boundary it meets.

The numeric anchors in this passage — the minutes
scale, the one-hour cap, the justification threshold —
carry their measured basis in the estimate evidence
register (`docs/estimate-evidence-register.md`). An
anchor with no basis recorded there is unbacked, and an
unbacked anchor is struck or marked, never silently
carried.

An item that
passes its estimate without completing is overdue: the
owning thread actuates on it — re-estimates it with the
reason stated, staffs it, or escalates it — rather than
merely reporting it again. The estimate lint reads the
plan and todo surfaces the tree itself declares; an
entry with no estimate, an estimate over thirty
minutes without its justification, and a justification
naming none of the long-duration classes, are findings.

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

Replacement at the stall bound: a lane that misses one
progress-checkpoint interval is replaced, not
re-steered. The programme's coordinator names a successor
in the same movement the miss is measured, on the
same commission — the same work item, branch, and caller
lineage — and the successor begins work in that movement,
never at the next queue pass; the takeover is recorded in
the programme's plan record, and the stalled lane stands
down on that commission under the one-executor rule when
the successor claims it. Re-driving a stalled lane
happens inside the interval, never as a further wait past
the bound. A miss with no successor named and working is
a defect row naming the coordinator's non-response,
addressed to the parent thread. A verified owner-gated
wait is not a miss, and it is not non-response.

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
actual traffic, and the claim's verdict follows the
evidentiary rule (The record never verifies itself). The
row never escalates to the owner as a question. A
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
  void (The record never verifies itself). Sequencing
  choices, agent-clearable waits, and matters already
  decided are never blocked states.
- **Work record** — where progress is measured: the record
  the cadence reads.
- **Cadence** — conforming progress-checkpoints on the
  armed cadence while doing; one missed interval is a
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
unreported, terminal, unlanded. Idle is armed or doing work with no
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
outputs declaration the residual waits on. Recording
is not consumption: the collector stamps a terminal
state, and the outcome then sits silent unless the
launching seat polls for it. Consumption
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

Unlanded: a build the owning programme's own record
claims complete whose commits are not on main. The
claim is a progress-checkpoint line naming the commit
beside a completion word — a build stated complete, a
gate stated passed — and the measure is ancestry: the
tick checks the named commit against main, never the
claim's own word. A gate verdict is not a landing,
and a branch push is not one either: the transport
branch is the landing vehicle, not the landing. A
claim at least one checkpoint interval old (the
programme's declared cadence) with the commit still
off main raises the row to the owning coordinator; it
re-surfaces every run of the measure until the commit
lands, and escalates under the programme's declared
escalation bound like every other class. The row
clears on the landing itself — ancestry flipping —
never on a later checkpoint's say-so. A claim whose
commit cannot be measured (unknown object, no repo
derivable from the record) raises nothing: honest
absence over a guessed row. The record vocabulary
matches the measure: a built-but-unlanded cure is
recorded "built, unlanded", and "complete" and
"completed" in a checkpoint are reserved for
landed-on-main — a checkpoint that spends the closing
words on branch state manufactures the completion the
tick then believes.

The actuator ladder, in order; a message alone is
the weakest form and never counts as the act by
itself. Self-collect: for a terminal-but-uncollected
record, read the result and deliver it with its
verdict — for the underivable orphan shape this rung
stays a coordinator act. Direct
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
the same run. A gap
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

The fan-out's form: the ruling states what is serial
first, if anything, then the fan-out. The fan-out is N
editors over M worktrees — the plan declares its editor
count and its worktree count independently, editors
share worktrees, and the pairing of one worktree per
editor, N equal to M, is excluded. The worktree count
is a formation decision, bounded per formation group
against a current base, never derived from the editor
count. Editors are spawned when the fan-out is declared,
before the serial prefix completes: they wait for the
go, and while waiting they gather the context their
branch touches — the files, the contracts, the
codebase — so edits begin the moment the go arrives,
with no ramp-up. The form's purpose is cost: editors
composing over shared worktrees collide as they go, in
the open, rather than at a landing boundary, and the
composed tree gates once — parallel work pays neither
merge-conflict costs nor merge-driven re-testing. Its
wall-clock is that ruling's critical path: serial prefix
plus longest parallel branch plus fan-in.

One executor per plan: an adopted plan names its executing
lane in its header, before its first edit — that edit is
the claim. A lane that finds a plan claimed by another
lane, or uncommitted changes on a plan's critical files,
stands down and surfaces the collision rather than
building in parallel on the same files. An open offer to
execute is completed by naming the executing lane when the
offer is taken up; an offer taken up in two places executes
on the first claim.

Formations are bounded by construction: worktrees and
branches are commissioned per formation group against a
current base — the rows of a group share one worktree and
its transport — never one long-lived worktree per row or
per base. Parallel worktrees on diverging bases
manufacture composition collisions at landing; a
formation that outgrows its group's bound splits by
file-set, not by row.

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
requirement. Lanes fan in as union trees, and where a full
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
whose pre-state is not yet known. The union is also the
dispatch default, not only the landing form: work
standing in a gate queue is dispatched as one union fire
by the dispatcher itself, and the fire's record names
its constituents — per-item gate queues are abolished.

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

A gate job runs its scoped check once. A second run
happens only as a re-proof: once, inside the same fire,
on a red verdict — never as a standing double run, whose
measured catch rate is zero. The verdict the record
carries is the fire's single run, or the re-proof's where
one ran.

Fires dispatch only over the runner's authorized routes,
and every fire's record carries its outcome class:
`manifest` (the job's own declaration failed validation
before transport), `transport`, `launch`,
`dispatch-blocked` (no route could fire it), `ran-red`,
`ran-green`. The manifest is validated before transport,
so a malformed job dies at the cheapest phase and is
priced there. A fire that produced no verdict is read
from its class, never retried blind: an identical re-fire
is the defect class the standing forms already name.
Dispatching around the runner — a bare direct execution
of the job's payload — is the anti-form: it produces no
record, no class, and no verdict the supervision measure
can read.

These disciplines bind where there is no plan file,
through the planless form's own instruments. On a defect
register, the row's staffing and formation fields carry
the formation bound and the union form, its gate and
resolution fields carry the fire's accounting, and its
closed rows are the priced history the next estimate
reads. In a goal file's standing execution form, the
recurring-defect classes carry the same disciplines as
standing dispositions with instance counts, and the
supervision measure verifies what the shared records can
see. A mechanical refusal that attaches to a plan's step
blocks — a plan gate's formation check — has no planless
reach; its contract twin, the grouping act at staffing
and the standing form itself, is the carrier in both
planless forms, and the record names that asymmetry.
Wall-clock counters read
the home repo's landing records; another form's phase
accounting stands in its own records — the register
row's closure fields, the lane's state record — until a
record family covers it.

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

A venue's finite capacities — its pid and thread budget,
its concurrent connections, its sessions — are declared
in its definition, not discovered at runtime. A consumer
that cannot state its footprint against the declared
budget is not ready to fire on a shared venue.

Sizing counts every pool the job brings: its declared
workers and the thread pools its libraries create at
startup, capped in the job's environment where the
venue's declared budget requires it — a pool sized to
the host's core count alone is not sized. A consumer
whose startup claim is a large fraction of a shared
venue's budget is a defect in the consumer: the claim is
measured by census of the holding process (thread names,
wait state, creation pattern) and cured at the consumer —
engine pool caps or the suite's own executor sizing —
before any rise of the venue's declared budget is
entertained. Process sharding multiplies a
per-process claim rather than dividing it; machine
sharding divides the container count, not the claim.

The declaration a venue checks before dispatch states
the claim in countable terms: workers × (the library
base at its stamped caps + the per-connection pools at
their stamped thread counts) + a controller and
subprocess allowance. Each term is measurable, and the
stamped counts are the ones the job's environment and
its own factories actually apply.

Admission is arithmetic, not discovery: before dispatch
the venue sums the declared footprints of the work it
would hold against its declared budget, and work that
does not fit waits. A table found full mid-run is an
admission defect — every admitted claim was declared in
advance, so saturation by co-tenants inside their
envelopes is the admission's failure, not a tenant's.

Dispatch routes by the measured curve: a venue's
concurrency cap for gate-class work is set from its
measured contention curve — gate-class work routes to a
venue up to its measured knee, with headroom, and work
beyond the cap spills to the next venue under the
load-aware rule. Admission decides whether work fits a
venue's declared budget; the cap routes the class
across venues. The curves and their knees are untracked
bindings per fleet, held with the venue definitions:
the spec carries the form, never a machine's name or a
measured value.

Venue state is classified on a generic contract, the same
for every venue kind: idle, advancing, saturated, wedged.
Sampled CPU-time progression and pids against the
declared budget are its instruments. The classification
actuates: a wedged run is reaped at its timeout and
killed on frozen evidence, the evidence going to the
owning lane; dispatch holds at saturation; idle capacity
is surfaced to staffing. Diagnosis is the runner's,
automatic — no venue's state waits on a manual check.

## Status vocabulary

A status report is grouped, never a bare code: it carries
exactly the groups its state selects, one line per group,
a group with nothing to report omitted and never filled
with a placeholder. The done group names the work items
flipped since the last report wherever work items exist;
summary-form done is legitimate only at the two closing
states. Completion words are measured words: in a
checkpoint or a report, "complete" is reserved for
landed-on-main, and a built-but-unlanded item is stated
"built, unlanded" — the unlanded gap class reads the
record on exactly this vocabulary. Work running past an
hour while its thread stays active states itself under
stalling — long-running is self-stated at the hour, not
discovered after the fact.

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

A lane's stop is a claim, read from its stated cause. A
stop whose stated cause matches a ruled agent-clearable
class is void as a stop: the supervising sweep applies
the class's standing disposition in the same pass that
detects the stop, and the stop never becomes an owner
item. The class register is closed: a class enters it
only by an owner ruling, recorded with its matching
form, its disposition, and its proof. The register
itself is deployment data, held beside the supervising
machinery in the form this text fixes; its content
changes only by the ruling that admits a class. The
ruled dispositions are the standing forms — an
execution-risk flag re-routes its flagged output in the
same movement and the lane continues; an agent-clearable
wait clears within the original approved scope; a missed
progress interval staffs its successor in the same
movement. Actuation requires a positive exact match of
the stated cause against a register form; an
unrecognized cause surfaces and is never actuated on a
guess. The hard-stop register bounds the mechanism
absolutely: a stated cause naming a hard-stop class is
refused before any class match is attempted, so no
actuation path exists from an owner-class stop. Every
actuation carries its proof — the lane's next conforming
progress record naming the disposition's effect — and an
unmet proof escalates; it never retries silently, and it
never converts the stop into an owner item.

## The record never verifies itself

An owner-block claim is verified against owner traffic
and the hard-stop register only. The claiming lane's own
records — its status records, its checkpoints, and every
cadence copy of them — are the claim restating itself
and carry no evidentiary weight, however many files
repeat them. The default verdict on an owner-block claim
is false: it is true only when it cites the owner's
actual message, identified by thread and time, and that
citation verifies against owner traffic the system
holds, or when it names a hard-stop-floor act that
exists. An uncited or unverifiable claim is void on
detection: the lane resumes under standing authorization
in the same pass, the frozen interval is priced and
recorded as a defect against the stamping seat, and the
voiding is never posed to the owner as a question nor
left standing as true pending review. A stop's state
string parses by exact match against the canonical
status vocabulary; a near-miss string is an unrecognized
signal that escalates to judgment, never a guess toward
an owner block, and an absent or corrupt signal never
reads as one. A struck classification restated as
present-tense fact in derived or standing context is the
same void claim, not corroboration, and is struck or
flagged in the same pass that voids the claim.

## Handler freshness

A handler registry's rows carry a served currency
verdict, composed by the one component that holds every
truth source — the reconciler — and consumed by surfaces
without derivation. The verdict set is fixed: `current`,
`stale`, `dead-binding`, `unresolvable`,
`retired-with-cause`. Composition reads only named
sources: the live chat census, the bindings registry,
the seat-truth owners files, and the handler's own
postings; run-record caller attribution is corroboration
only — it can support a verdict when its resolution
agrees with the binding, and its absence never marks a
handler stale or dead. A verdict older than two
reconcile cycles renders `stale` regardless of content;
evidence windows are short for programme seats and long
for lanes, because a quiet lane is not a dead one. A
handler no source covers is `unresolvable`, never
interpolated: no chat id, lane, or venue is invented to
fill a row.

Residue — bindings and owners rows naming deleted or
superseded seats — leaves by a recorded disposition,
never a guess and never an open-ended escalation of rows
whose seats are already known gone: each row is retired
with a cause from the fixed vocabulary (`seat-deleted`,
`superseded-by <handle>`, `lane-dissolved`), the cause
carried verbatim in the served record thereafter, and
the reconciler reports the row resolved, not drift. A
row whose cause cannot be stated from the record stays
`unresolvable` and is named once, with its evidence.

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
programme is complete only when its armed entries are
terminal and no worktree stands unlanded. Blocked
claims come from blocked todos: the todo's status is
`blocked`, its basis is in
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
measure serves.

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
is not a valid separator either. Wrapping behaviour is
consistent across surfaces of a kind. A summary never
repeats its title: title and
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
