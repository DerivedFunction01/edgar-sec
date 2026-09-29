# `edgar_sec/engine/forms/plugins` — the `FormPlugin` SPI and its registry

The extension seam that makes the normalization chain form-aware without giving any form its
own pipeline. A form family supplies *data* — a cover checkbox schema, a set of boundary
signals, two structural toggles — and *hooks* — a content transform and an evaluator — and
the single chain in `edgar_sec/engine/forms/normalize.py` consults them at fixed points.

This is new in Phase 2.5. It replaces v1's per-family pipeline classes, where the stage order
was duplicated per form and could drift.

## Purpose

Answer one question — "what should the shared chain do differently for this form?" — with a
value, not a subclass. `FormPlugin` is a frozen dataclass, and `get_plugin` resolves a raw
form string to one in three steps.

It does not run anything. The chain calls the plugin's callables; the plugin never calls
the chain. That asymmetry is what keeps the stage order in exactly one file.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | The `FormPlugin` dataclass, the two callable type aliases (`ContentTransform`, `Evaluator`), and the `GENERIC_FAMILY` key. 50 loc. |
| `registry.py` | The seeded table of four plugins, the three boundary-signal profiles, the lazy evaluator binder, and the lookup. 145 loc. |

## Public surface

- `FormPlugin` — frozen, slotted dataclass with six fields: `family`, `cover_schema`, `boundary_signals`, `enable_body_start`, `transform_content`, `evaluator`. `edgar_sec/engine/forms/plugins/models.py:31`.
- `GENERIC_FAMILY` — the family key `"GENERIC"` used when a form has no modeled profile. `edgar_sec/engine/forms/plugins/models.py:20`.
- `ContentTransform` — `Callable[[str], str]`; a per-form hook that rewrites already-normalized text and **must be pure**. `edgar_sec/engine/forms/plugins/models.py:24`.
- `Evaluator` — `Callable[[str], EvaluatorDecision]`; a per-form hook that triages normalized text for stub/delegation content. `edgar_sec/engine/forms/plugins/models.py:28`.
- `get_plugin` — resolve a raw form string to a plugin. `edgar_sec/engine/forms/plugins/registry.py:111`.
- `register_plugin` — register or override a family's plugin. `edgar_sec/engine/forms/plugins/registry.py:103`.
- `registered_families` — the families that currently have a modeled plugin, sorted. `edgar_sec/engine/forms/plugins/registry.py:136`.

## What a plugin controls

| Field | Effect in the chain | Where consulted |
| :--- | :--- | :--- |
| `boundary_signals` | The `BoundarySignal` tuple passed to `find_cover_boundary`. Empty disables cover parsing entirely. | `normalize.py:262` |
| `cover_schema` | Non-`None` enables the whole checkmark stage. `None` skips extraction, solve, and rewrite. | `normalize.py:274` |
| `enable_body_start` | Whether `find_body_start` runs at all. | `normalize.py:301` |
| `transform_content` | Runs between the checkmark stage and final whitespace, on the full document text. | `normalize.py:292` |
| `evaluator` | Not called by the chain at all. Read by the pipeline after normalization. | `edgar_sec/pipelines/document_storage/processor.py:157-158` |
| `family` | Reported on `NormalizationResult.family` and passed to the checkmark solver. | `normalize.py:342`, `:278` |

## The seeded registry

Four plugins, keyed by the form string as it arrives (`registry.py:62-100`):

| Key | `family` | `cover_schema` | `boundary_signals` | `enable_body_start` | Evaluator |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `10-K` | `10-K` | `ANNUAL_CHECKBOX_SCHEMA` | all seven | `True` | `evaluate_annual` |
| `20-F` | `20-K` | `ANNUAL_CHECKBOX_SCHEMA` | all seven | `True` | `evaluate_annual` |
| `10-Q` | `10-Q` | `QUARTERLY_CHECKBOX_SCHEMA` | five (no `TOC_TRANSITION`, no `INCORPORATED_REFERENCE`) | `True` | `evaluate_quarterly` |
| `8-K` | `8-K` | `None` | two (`COVER_IDENTITY_AND_LAYOUT`, `PAGE_MARKERS`) | `False` | `evaluate_current_report` |

The `20-F` row deserves a second look, because it looks like a bug and is not:
`family="20-K"` (`registry.py:73`) while the lookup key is `"20-F"` (`registry.py:72`). The solver's
`_schema_for_family` (`edgar_sec/engine/forms/checkmarks/solver.py:160-168`) branches on
`{"10-K", "20-F"}`, so the reported family would take the *quarterly* branch — but the
plugin's `cover_schema` is passed explicitly at `normalize.py:280`, which short-circuits
`_schema_for_family` entirely, so the schema in force is the annual one. The `20-F` key
reaches the annual evaluator and the annual schema; only the `NormalizationResult.family`
string says `20-K`. Anyone correcting this must correct the solver's family branch in the
same change.

## Contracts

- **The chain reads the plugin; the plugin never calls the chain.** Every plugin field is
  either data or a `str -> str` / `str -> EvaluatorDecision` callable
  (`models.py:22-28`). There is no lifecycle hook and no stage-order override. This is
  stated as the package's reason for existing (`models.py:3-8`): a form family supplies data
  and hooks so that the stage order lives in exactly one place.
- **A `ContentTransform` must be pure.** `models.py:22-23` specifies it receives and returns
  the full document text and *must be pure*. The chain calls it once, at
  `normalize.py:292-294`, and records a stage-trace entry only when the text changed.
- **Evaluator hooks are bound lazily and resolved by string path.** `_lazy_evaluator`
  (`registry.py:48-55`) closes over a module path and an attribute name and calls
  `import_module` on first use. The docstring gives the reason: importing the registry never
  pulls in evaluator modules, keeping the engine import graph acyclic and import cost flat.
  The cost is that a rename breaks the binding at call time, not import time.
- **Lookup degrades, it does not raise.** `get_plugin` (`registry.py:111-133`) resolves in
  three steps: (1) `resolve_alias(form)` from `edgar_sec/domain/forms/families.py`, then an
  exact registry hit; (2) `form_family(form)` — the suffix-stripped form — then an exact
  hit; (3) the raw uppercased string, then the generic plugin. `None` and the empty string
  return the generic plugin immediately.
- **Step 2 is what makes runtime-registered families reachable by their amendment forms.**
  The docstring states the reason explicitly (`registry.py:114-118`): the alias table in
  `edgar_sec/domain/forms/families.py` is static and cannot know about a family added later
  by `register_plugin`, so `S-4/A` still resolves to `S-4`.
- **`register_plugin` uppercases and strips its key, and rejects the empty string**
  (`registry.py:103-108`). It mutates module-level process state: there is no registry object,
  no context manager, and no unregister. A test that registers a family changes the registry
  for every later test in the same process.
- **The generic plugin disables the two things that need a cover.** `_default_plugin`
  (`registry.py:58-59`) returns `FormPlugin(family=GENERIC_FAMILY, enable_body_start=False)`
  with no `cover_schema` and no `boundary_signals`. An unmodelled form therefore gets no
  cover parsing, no checkmark stage, and no body anchor — it is normalized but not
  structurally interpreted. That is the stated degradation path: "a new SEC form type
  degrades to no cover handling" (`registry.py:120-121`).
- **Obligations on callers.** A caller that wants form-specific behaviour must pass a form
  string the alias table recognises. A caller that wants to change behaviour permanently must
  call `register_plugin` before the first `get_plugin` for that family, and must accept that
  the change is process-global.
- **No barrel re-exports.** `edgar_sec/engine/forms/plugins/__init__.py` is a one-line
  docstring (`"SEC form structural plugins (item taxonomies and boundary profiles)"`).
  Consumers import from `plugins.models` or `plugins.registry` directly, per AGENTS.md §1.2.

## Tests

- `tests/engine/forms/plugins/test_models.py` — 4 tests over the dataclass contract and defaults.
- `tests/engine/forms/plugins/test_registry.py` — 9 tests over lookup order, alias resolution, and override behaviour.
- `tests/engine/forms/test_normalize.py:213-222` — alias resolution through the chain (`get_plugin("10-K405").family == "10-K"`, `get_plugin("8-K12B").family == "8-K"`) and lazy evaluator reachability (`get_plugin("10-KSB").evaluator(DOC_10K)`).

## Deliberate gaps

- **The SPI carries no item taxonomies, despite what the package docstring says.**
  `edgar_sec/engine/forms/plugins/__init__.py` advertises "item taxonomies and boundary
  profiles", but no Part/Item taxonomy exists in v2. The generic matching in
  `edgar_sec/engine/forms/cover/structure.py` accepts Roman or decimal Part labels and
  arbitrary decimal Item labels precisely so a future form can be added without editing it
  (`structure.py:99-101`), but nothing enumerates which Items a given form actually has.
  v1's `defs/sec_forms/forms/annual/taxonomy.py` (`PART I`–`PART IV`, `ITEM 1`–`ITEM 16`),
  `forms/quarterly/taxonomy.py`, and `forms/current_report/taxonomy.py` were not ported.
  Roadmap Phase 03 (Canonical Item Segmentation & TOC Spine,
  `roadmap/master_roadmap.md`) is where statutory item state machines are meant to land;
  this package is not their home.
- **No plugin implements `transform_content`.** All four seeded plugins leave it `None`, so
  the chain's stage-6 hook (`normalize.py:292`) never fires for a registered form. The field
  is part of the contract and is exercised only if a caller registers a plugin that sets it.
- **`register_plugin` is not reversible and not scoped.** No unregister, no context manager,
  no fixture helper. A test that registers a family mutates module state for the rest of the
  process; anything that needs isolation must save and restore `_PLUGINS` itself.
- **The registry is a plain dict, not a declared dynamic registry.** AGENTS.md §1.2 permits
  true dynamic registries in `__init__.py` (naming `ALL_SCANNERS` as the example); this
  registry lives in `registry.py` instead and is reachable only through `get_plugin`. There
  is no discovery scan and no decorator-based self-registration, so a new plugin is invisible
  until someone edits `_PLUGINS` or calls `register_plugin`.
- **Only four families are modeled, against a roadmap that promised more.**
  `phase_2_5/04_engine_tables_and_forms.md` §1 names "10-K, 10-Q, 8-K, 6-K, 20-F, Form
  3/4/5, and Form 13F". Shipped: 10-K, 20-F, 10-Q, 8-K. `6-K` is a recognised family in
  `edgar_sec/domain/forms/families.py::FORM_FAMILY_ALIASES` but has no plugin, so it falls
  to the generic one — no cover parsing, no evaluator, and by extension
  `edgar_sec/domain/forms/decisions.py::DecisionAction.SKIP_HARD_STUB` is unreachable.
  Form 3/4/5 and 13F are XML forms with no cover page at all; the generic plugin is
  arguably the right answer for them, but it is an accident of the fallback rather than a
  decision.
- **The abstract-class SPI in the roadmap is not what shipped.** §3.3 of the same roadmap
  sketched `class FormPlugin(ABC)` with `evaluate()` and `normalize()` methods. What shipped
  is a frozen dataclass of data plus callables. The substitutability is the same; the
  inheritance is gone, and `FormPlugin` is not subclassable for extension — use
  `register_plugin` with a constructed instance.
- **No per-form evidence packs and no cover profiles.** v1's `CoverProfile` /
  `COVER_PROFILES` / `get_profile()` and its `CoverEvidencePack` / `BodyEvidencePack` base
  contracts are not ported. The boundary-signal tuple and the checkbox schema are the whole
  of the per-form configuration in v2, and the body-prose vocabulary is a single generic
  pack in `edgar_sec/domain/forms/body_evidence.py` — not per form.
- **No `normalize()` override.** A plugin cannot insert, remove, or reorder a stage. v1's
  per-family pipeline classes could; that capability was deliberately given up so the stage
  order would have exactly one definition (`normalize.py:26-28`).
