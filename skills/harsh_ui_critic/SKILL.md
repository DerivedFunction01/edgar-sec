# Harsh UI Critic

## Stand apart from the builder

- Run as a critic, not as the agent that built the UI: a separate session or agent issues the verdict, because a single evaluator grading its own work is a sample of one with a conflict of interest.

- Stay audit-only: report findings and verdicts, never fix in the same run, so the evidence behind a verdict is never the fixer's own recollection.

- Treat build success, green test gates, DOM presence, and uninspected screenshot files as supporting signals, never as visual proof — a page that looks cheap while every gate is green is the signature failure this skill exists to catch.

## Write the contract before judging anything

- Open every run by writing a falsifiable scope contract: the routes and flows in scope, the actor and job for each flow, the viewports, the states to exercise, the approved-design reference for each surface, and the pass condition.

- Name the approved design explicitly per surface — mock, frame, or prior approved build — or record "no approved design": the parity module is then skipped and the verdict for that surface is capped at `partial`.

- Refuse a verdict without a contract: an unscoped pass is an opinion, and an opinion cannot block or clear a release.

## Run in the standing shape

- The run's shape is part of the contract, recorded beside the scope: browser-driven legs execute on the project's parallel compute venue (Colab sessions where the project runs them), never on the local host while that venue is up; one audit lane per app or surface, the lanes running in parallel; screenshot evidence driven by Playwright or the project's named equivalent at desktop (~1440px), phone (~390px), and tablet (~768px) widths; both themes or appearances judged wherever the product has two.

- A commission that arrives in another shape is re-formed to the standing shape before the run starts: venue, lane split, widths, and appearances are requirements, not preferences, and a lane never quietly substitutes a smaller shape it can staff for the shape the contract names.

- Verify the shape can complete its own matrix before starting: the venue answers, one lane is staffed per in-scope surface, the browser launches on the venue, and the serve route serves the target build end to end — one route loads with real data. A shape that fails any of these is refused and reported as a run-shape failure: the run does not start, and no verdict issues from it.

- An incomplete matrix is never cured by disclosure: a run launched in a shape known to be incompletable — a single lane against a multi-surface matrix, a local host that kills the browser under load — has failed at the shape, not at coverage, and naming the unrun cells in prose does not convert that failure into a partial result. Unrun cells in a run that started in a valid shape are handled by the verdict computation, not by refusal.

## Grade evidence by level

- Level A: a real browser or native window driven through the actual journey, with representative data.

- Level B: the same state exercised through a browser-automation driver (Playwright or equivalent) with representative data.

- Level C: a headless mechanical sweep — screenshots and geometry per viewport, machine-collected.

- Level D: source, lint, build, and unit-test output — hypotheses and regression support only, never proof of appearance or behaviour.

- Count a screenshot as evidence only if you opened and inspected it in this run: a file that exists but was never looked at has no evidence value, and a fresh empty state cannot verify a populated one.

- Ship every appearance claim with its pixels: a crop at the affected element in CSS pixels, labelled with viewport, state, route, and the build it shows — a full-page screenshot proves nothing about a small misalignment.

## Enumerate what each instrument does not check

- Before the run relies on any gate's green — a project gate, a kit check, or one of the run's own scanners — record that instrument's enumeration boundary: the exact set it checks (which pairs, surfaces, rules, states, backgrounds), read from the instrument's own code or configuration, never from its summary line or its name.

- Everything outside a trusted instrument's boundary is in-scope for rendered review: the uncovered space joins the contract as cells the run must exercise itself, and the report names the boundary per instrument it relied on. A gate's green is evidence only inside its boundary; citing it outside the boundary is a reporting defect.

- Worked example: a kit contrast gate enumerated status and content text against the surface backgrounds only, and stayed green while the same text rendered on its own status tints failed the contrast bar on hundreds of nodes — the tint pairs were outside the enumeration, so they were the critic's to check, and no run had checked them. Every enumeration has such an edge; this leg exists to find it before the verdict leans on the green.

- The run's own instruments have boundaries too: a scan that reports counts without naming the rules behind them cannot be relied on for the rules it cannot name — record what each of the run's instruments does not report, and treat that space the same way.

## Run the mechanical sweep first

- Run the automated legs before the rendered review and attach their raw outputs to the report, never summarised away: a rendered layout sweep per viewport (overlap, overflow, geometry), an accessibility scan configured to the WCAG 2.2 AA rule set, and any deterministic rule detector the project pins.

- The sweep's evidence source is the project's standing rendered legs (`docs/checks.md`, Rendered legs) where the project carries them — the axe leg, the geometry leg, the truncation ruler, the dead-click sweep, and the parity leg over the surface census, entered through the committed shard runner: cite each leg's raw output by leg name, and treat a leg the project has not seeded, or a census route it has not enrolled, as unexercised, never as passed.

- Where the project carries the starter UI kit (`ui-kit/`), its contrast gate (`ui-kit/tools/verify-contrast.mjs`) is a pinned instrument of the sweep: cite its per-part pair counts from its own output, and record its enumeration boundary from its header — the pair classes it prices (text on surfaces, tints, and solids; focus and control boundaries; component mix states) and the spends its censuses classify rather than price. A kit surface the gate's census has not classified is uncovered space, in scope for the rendered review like any other instrument edge.

- Treat a clean automated run as covering only the machine-checkable subset: it clears its own findings and nothing else, and is never reported as "accessible" or "finished".

- Propose a scanner or detector rule for every confirmed defect class that is mechanically detectable, so a class caught once by eye becomes a class caught forever by the gate.

## Review the rendered page, route by route

- Inspect every in-scope route at each contract viewport — the default matrix is a small phone (~390px), a tablet (~768px), and a desktop (~1440px) — including the sections below the fold.

- Exercise the state matrix on every route, not just the default state: loading, empty (first-use distinguished from no-results and from unavailable), error, disabled, success, and permission-denied where the surface has one.

- Check the per-state quality bars: loading prevents duplicate actions; empty states say which kind of empty it is; errors preserve the user's recoverable input and say whether a retry is safe; disabled controls say why they are disabled.

- Judge composition, spacing rhythm, overlap and overflow, typography, and image quality on the rendered pixels, in both themes wherever the product has two — dark mode is its own pass with its own contrast pairs, never a toggle screenshot.

- Measure, never estimate, the numeric bars: text contrast at least 4.5:1 (3:1 for large text and for non-text UI contrast), primary-action targets at least 24×24 CSS px with mobile primary actions expected at 44×44, and no horizontal overflow or obscured content at any named viewport.

## Compare against the approved design, not the build's own baseline

- Where an approved design exists, put the design and the rendered build in the same comparison at the same viewport, state, theme, and scale before judging either — never grade from separate views, memory, or file paths.

- Walk the five fidelity surfaces in order: typography, spacing and layout rhythm, colour and tokens, image quality, copy and content.

- Close the comparison with an explicit original-vs-current checklist per surface — improved, missing, or not implemented with a recorded reason — so no gap between the approved design and the build passes silently.

- Remember the split: regression tooling answers "did it change?", this module answers "does it match what was approved?" — a build that was never right passes every regression gate forever, and baselines are never auto-approved or auto-updated.

## Walk the journeys as personas

- Accept a flow only by walking it end to end as each persona the contract names — including the staff and admin sides where they exist — performing the real job (book, pay, reschedule, dispatch) in a real browser, and recording where friction appears.

- Walk the primary flow by keyboard alone at least once: tab order must be logical, focus must be visible, and focus must never be entirely hidden behind sticky headers, banners, or overlays.

- Trigger every relevant control: a visible signifier is not proof of a handler, and a dead click is confirmed only by clicking.

- Count the interaction cost of each task — clicks, taps, swipes, and repeated entries — and flag any control that forces many small steps where a direct manipulation exists (a stepper where the value itself could be edited, a flow that re-asks known information).

- Audit irreversibility: find every place one wrong tap can make a decision that cannot be undone, on every persona's side, and flag missing confirmation or undo.

## Audit consistency and defect classes

- Treat every confirmed defect as a class, not an instance: search every surface for the same class before reporting, and report the class with its full occurrence list — "how many places are like this?" is the question the critic answers, not the owner.

- Check one primitive owner per concept: the same concept (time, dates, buttons, prices) implemented several ways across surfaces is a finding in itself, as is a raw platform primitive appearing where the design system has a component for it.

- Compare surfaces that share a design language against each other — tokens, type, state vocabulary, header and chrome — and flag any surface lagging an approved change another surface already carries.

- Read every label and control name as a user would: a label that names nothing, a count rendered as nonsense, or a free-text field where the domain has a structured value are quality defects, filed like any other.

- Build an input-pair matrix for any class that depends on data combinations (the pairs of values that co-occur), and automate the matrix where the project's harness allows it.

## Run the polish census

- Run this census on every run, over the same rendered surfaces as the rendered review: it is a conformance pass over structure — affordances, layout stability, sheets, lists, headers, labels, control chrome, and form structure — not a journey, and persona legs never substitute for it. A surface can pass every journey and fail this census; that failure is a verdict input like any other.

- Produce rendered evidence at phone width for every leg: a leg that cannot produce evidence is recorded as unexercised, never passed, and an unexercised census leg is named in the report as plainly as an unexercised contract state.

- Census leg — action affordances: within any card, row set, or sheet, actions of the same class render the same affordance; a navigation action styled as a bare text link beside a button-styled commit action is a finding, as is any same-class pair a user has to read twice to tell apart.

- Census leg — empty-state layout stability: render every form and card twice, empty and filled, and compare control positions between the two renders; any control that moves, resizes, or changes row when a field is blank is a finding — layout is graded on the empty render as strictly as on the filled one, because first use is always empty.

- Census leg — sheet conformance: exactly one sheet implementation serves every surface; measure each sheet against it — top-corner radius, grab handle, padding rhythm — and exercise every sheet with content tall enough to outgrow the viewport: a sheet that cannot scroll internally, or that traps or cuts off an entry, is a finding.

- Census leg — list structure: a list that carries a per-item action renders as structured rows, never as prose bullets with the action embedded in the text; the action is sized to its row — an icon or a small button — and a full-width button inside a list item is a finding on its own.

- Census leg — header actions: no full-size button shares a line with a section or page header; a header's actions live in a defined slot at icon or small-button size, or on their own row below the header — a button jammed against a heading is a finding even when nothing overflows.

- Census leg — duplicate labels: within one menu, sheet, or page, identical visible labels must name the same destination or action; two different destinations sharing one label is a finding, and the census lists every label collision it finds, not just the first.

- Census leg — control chrome, extended: the browser-default lens covers every control class, not only tables — segmented toggles, previous/today/next navigation groups, selects, and file inputs at every calendar, editor, and settings surface are the design system's control at the standard size; a default-looking control, or a bespoke control at a non-standard size, is a finding.

- Census leg — parameter completeness: a row, chip, or label that names a state whose meaning depends on parameters shows the parameters — a behaviour named "extended break" with no date range on the row, a limit with no number, a schedule with no hours is a finding: the name alone is not the state.

- Census leg — form structure: a multi-section form reads as grouped sections — dividers or visible grouping, one section vocabulary, and a per-section state summary (set, not set, needs attention) visible without opening the section; a stack of undifferentiated bars with no grouping and no state is a finding even when every field inside it works.

- Coverage rule for the census: every admin and settings surface is exercised at phone width as well as desktop; a surface visited only at desktop width is unexercised for this census and is reported that way. Horizontal overflow at phone width is measured by the mechanical sweep's geometry leg — cite its output here rather than re-measuring it.

- Anchor leg — external anchors: reference-first is the standing rule — a surface's design is anchored on the mass-market app whose pattern governs that surface class, unless the record shows a deliberate, ruled departure. Before judging any surface, name its anchor; the run report carries an anchor map (surface → anchor) for every surface exercised, including surfaces with no anchor finding.

- Anchor leg — anchor provenance: take anchors from, in order, (1) the project's own record — a ruling or study that names the reference; then (2) the obvious platform governor for the class — the dominant calendar apps for calendars, the dominant payment dashboards for money forms, the operating-system settings idiom for settings, the spreadsheet app's workbook conventions for spreadsheets and exports, and the dominant accounting or payment dashboards for finance dashboards. A pattern proven in the owner's other shipped products and recorded for this project is also an anchor source: for a class with a named external governor it ranks below that governor, and above an unanchored invention. Familiarity or taste is not a source.

- Anchor leg — UNANCHORED: a surface for which no anchor can be named is filed as UNANCHORED — an invented-shape risk. The finding proposes an anchor for the owner's ruling; the critic never silently adopts its own nomination.

- Anchor leg — DIVERGENT: a surface that departs from its anchor's pattern with no ruled departure on record is filed as DIVERGENT. The finding names the anchor pattern and the divergence; a ruled departure, cited, closes it.

- Anchor leg — anchor evidence: evidence the anchor pattern like any other appearance claim — a rendered capture or a precise, checkable description of the reference pattern, never an appeal to taste. Where the reference cannot be rendered in the run's environment, the anchor leg is unexercised for that surface, never passed on memory.

- File census findings in the standard finding schema with the leg named as the category, and propose a scanner rule for every census class that is mechanically detectable — label collisions, prose-bullet lists carrying actions, and header crowding are DOM-checkable, and a class caught by eye once should not need a human eye twice.

## Why the census is graded on evidence

- Persona journeys alone miss structural polish: they follow tasks, not surfaces — a surface visited only at desktop width, or only ever rendered with filled data, is effectively unvisited. The census legs close exactly those holes: surface-by-surface coverage, phone width, empty and filled renders.

- Every census run is graded on evidence, not findings: a run whose legs produce no rendered evidence on the surfaces they cover has failed, even when it reports no defects. A run that finds nothing and evidences nothing has not run the census.

## Stress with hostile data

- Feed the hostile leg production-shaped fixtures sourced from the surface's own served data, never invented payloads: before the leg runs, capture the payloads the surface actually serves — the same reads the rendered review drives — and draw the fixtures from that capture.

- Set the floor from reality: for each data dimension the surface renders — payload and text length, list size, label and copy length, numeric magnitude — the fixture set includes the longest or largest real example the capture observed, verbatim where the harness allows. A synthetic extreme the product never serves tests a product that does not exist, and a tidy synthetic payload misses the shape that actually breaks rendering: a log-row class shipped broken on a real long command payload from the live app while every run's clean fixtures passed it, surfacing only when the owner screenshotted the live breakage.

- Grow real copy the way localisation will — translations run roughly a third longer than the default language — applied to the captured strings, not to invented ones, and re-run the primary routes under the grown set before verdict.

- Combine stressors the way users will meet them: a validation error visible at the same time as long content, at the smallest viewport, in both themes.

- Add the environment stresses: 200% zoom or equivalent reflow, reduced-motion preference honoured, and a slow-load state that cannot be mistaken for a dead page.

## Apply severity, hard blocks, and the closed verdict

- Rate every finding on one unified severity scale: Blocker (the task cannot complete, a false success, a destructive or misleading action, a severe accessibility failure, or a layout break hiding controls), Major (a core task, recovery path, or critical control unusable, or a major mismatch against the approved design), Moderate (user-visible drift, an inconsistent state, a responsive defect), Minor (polish).

- Block the release on any unresolved Blocker or Major, and on Moderates that sit in a primary flow or on a primary task; three or more Moderates on one route also block that route.

- Apply the hard binary blocks with no discretion and no averaging: any critical or serious automated accessibility violation at WCAG 2.2 AA; any measured contrast or target-size failure against the bars above; any horizontal overflow or obscured content at a named viewport; any contract state left unexercised (the verdict is capped at `partial`); any in-scope route with no inspected screenshot (that route is `blocked`); an approved design exists but the parity module did not run (`blocked`).

- Compute the verdict from the run's matrix record, never narrate it: the record lists every contract cell — route × viewport × state × appearance, plus each census leg, journey, and hostile leg — marked exercised with inspected evidence, exercised without inspection, or unrun, and it is attached to the report as a run artefact.

- Derive the cap mechanically, in this order: any unrun cell that leaves an in-scope route without an inspected screenshot makes that route `blocked`, and one blocked route makes the run `blocked`; any other unrun cell or unexercised contract state caps the run at `partial`; `passed` requires a matrix with zero unrun cells. The issued verdict is the more severe of the findings verdict and the matrix cap.

- Prose disclosure does not soften the cap: naming an unrun cell in the report is required honesty, but the cap is computed from the record whether or not the prose mentions it, and a confident narrative over an incomplete matrix is a reporting defect.

- Issue the verdict in the closed vocabulary only: `passed`, `partial`, or `blocked` — `passed` requires the contract fulfilled, every viewport and state exercised at Level A or B, and no finding that blocks under the rules above.

- Report heuristic scores (a Nielsen-style heuristic total, a technical audit total, performance and accessibility smoke scores) under the verdict as context: a strong total can still contain a blocking issue, and no score ever raises a verdict.

## Close fixes with proof, not assertion

- Close a finding only on a re-run at the same target, state, and viewport, with identical-crop before/after evidence attached.

- Require the regression guard for a closed defect class to be proven capable of failing: reintroduce the defect once and watch the guard go red, or the closure is a claim, not a proof.

- Record the comparison history per release in a durable QA artefact in the project, so the next run starts from what was already judged instead of re-deriving it.

## Load the project layer

- Read the project's instance file before the contract step whenever one exists for the project under criticism: it declares the project's flows and personas, its approved-design locations, its exemplar set, and its own defect taxonomy with the classes that project has actually shipped.

- Let the instance add hard blocks and named checks; never let it relax the generic bars, the evidence rules, or the verdict vocabulary.

- Keep project facts out of this core: a defect class enters the generic skill only when it is stated without any project's names, surfaces, or history.

## Report in the finding schema

- Write every finding as one record: severity, category, route, state, viewport, reproduction steps, the evidence crop, and the expected behaviour or approved-design reference it violates.

- Order the report by severity, state the verdict first, and name what was not exercised as plainly as what failed — an honest `partial` outranks a confident `passed` the evidence cannot carry.
