# S10 Form-Family Processing Decision Tree

**Status: proposed.** This document describes per-target acquisition operations and
processing outputs; it is not implemented behavior. The profile contract is planned in
the [S6 acquisition-policy plan](../document_planning/acquisition_policy_plan.md). Reconcile
this proposal with the existing [S10 processing contract](../S10_processing.md) before
implementation.

## Boundaries

One S6 target is one logical SEC document. Its policy may request one or more operations:
raw preservation, rendering to text, or a supported XML result. S9 acquires the source
body or bodies needed by those operations. Processing outputs are grouped under the
logical document; they are not duplicate document targets.

- **Document planning** pins an explicit operation set or requests the default operation
  priority. It does not read document bodies or make network requests.
- **S9 acquisition** fetches each distinct source input required by the planned
  operations. Multiple operations that consume the same source bytes share one fetch.
- **S10 processing** produces the requested supported output representations and records
  each operation outcome. It cannot fetch an unplanned URL or change the selected S6
  target.
- **XML remains opaque in acquisition processing.** A source XML result is passed through
  unchanged to a separate form-specific XML pipeline. `render_to_xml` is an operation
  name, not a promise that acquisition parsed or translated XML.
- **The old `document_storage.FilingProcessor` is frozen legacy.** Reuse its lessons, not
  its selection behavior or module.

The profile operation policy and the family/file-route capability registry are distinct.
The policy says what outputs are wanted; the registry says which operation implementation
exists for the form family and effective route.

## Operation resolution

The closed operation vocabulary is `raw`, `render_to_txt`, and `render_to_xml`.

- With an explicit policy, execute every listed operation implemented for the selected
  form family, target role/type, and effective file route. An unsupported operation is
  ignored for execution and recorded as not supported/not applicable; it does not fail
  other supported operations.
- With no explicit policy, choose the first implemented operation in this default priority:

  ```text
  render_to_xml > render_to_txt > raw
  ```

- “Implemented” means a registered capability for this family and route, not that a
  particular source path or conversion is guaranteed to succeed. Once an operation is
  chosen, a failed fetch or transform is recorded; it does not trigger an implicit
  operation or URL fallback.
- S9 retains acquired source bytes for integrity and replay regardless of the output
  operations. `raw` additionally exposes those bytes as a stored representation; it does
  not duplicate the acquisition body.

Capability registration is versioned and participates in processing identity. A change in
operation support or default resolution cannot silently change an existing stored result.

## File-route operation matrix

Resolve the effective route from the selected path and response metadata. The path matters:
`xsl*/.../*.xml` is an HTML rendering despite its `.xml` suffix, while flat `.xml` is the
source XML path.

| Effective file/path class | Operations |
|---|---|
| Images, `.fil`, `.zip`, `.eis`, `.paper` | `raw` only; ignore rendered operations. Paper records its raw/no-content state. |
| `.pdf` | `raw`, or `render_to_txt` when a PDF text extractor is registered. |
| Flat `.xml`, `.xsd` | `raw` only. Pass bytes unchanged to a separate form-specific XML pipeline. |
| `xsl*/.../*.xml` | `raw` returns the rendered HTML response; `render_to_txt` generically strips HTML and projects tables; `render_to_xml` resolves the same accession's archive-root XML path by stripping the XSL prefix and acquires that source unchanged. |
| `.txt` | `raw` or a supported `render_to_txt` view. |
| `.htm`, `.html`, `.xhtml` | `raw` or generic `render_to_txt`; a registered form-specific translator may add `render_to_xml`. |
| Unknown route | `raw` only unless a family and route capability is registered. Do not coerce unknown content to prose. |

For XSL `.xml`, `render_to_xml` is a source-path operation, not an XML parser. Its
archive-root URL is an additional S9 fetch dependency. A `render_to_txt` result derived
from the XSL response shares that response's acquisition input with the `raw` operation.

### Form 4

An XSL Form 4 path may produce HTML, and a corresponding archive-root XML source may
exist. The policy can request raw HTML, generic rendered text, the raw XML source, or
multiple supported operations. The XML source remains byte-identical for the separate
Form 4 pipeline.

Some Form 4 filings have HTML only, such as an accession-level `edgar.htm`, with no XML
source. That is a valid source case. A Form 4 HTML-to-XML translator is a possible
form-specific `render_to_xml` implementation, but it is deferred, unimplemented, and not
validated for accuracy. Until registered, that operation is ignored; the default policy
falls through to supported `render_to_txt` or `raw`. Do not synthesize XML or describe
HTML bytes as XML.

## Processing flow

```mermaid
flowchart TD
    TARGET["Pinned S6 logical target"] --> OPS["Resolve explicit operations or default priority"]
    OPS --> CAP["Resolve capabilities by family, role/type, and effective route"]
    CAP --> SOURCES["Materialize required source inputs"]
    SOURCES --> FETCH["S9 fetches each distinct input once"]
    FETCH --> GROUP["Group source records under StoredDocument"]
    GROUP --> RUN["Execute every supported operation"]

    RUN --> RAW["raw: expose exact source bytes"]
    RUN --> TXT["render_to_txt: render supported source to text"]
    RUN --> XML["render_to_xml: XML source path or registered form translator"]
    RUN --> IGNORE["Record unsupported operations as ignored"]

    RAW --> OUTPUT["Store operation outputs and provenance"]
    TXT --> OUTPUT
    XML --> OUTPUT
    IGNORE --> OUTPUT
    OUTPUT --> SNAPSHOT["Snapshot sources, outputs, and partial outcomes"]
```

The `render_to_xml` branch is route-specific: for an XSL `.xml` path, S9 acquires the
root XML source; for HTML-only Form 4, a form-specific translator would be required. The
root XML bytes are not parsed by acquisition. A translator result, if implemented later,
is a derived output with its own handler/version and quality evidence.

## Family-specific processing

### Primary reports

For a primary target with a registered cover profile, `render_to_txt` uses the family's
cover-boundary and normalization pipeline. Eligible forms currently include 10-K, 10-Q,
8-K, and 20-F; 6-K requires an explicit registered profile. Keep dispatch capability-based
rather than hardcoding a form list.

An early `find_cover_boundary_for_profile` probe can run before a conditional
misfile/exhibit diagnostic. Run that diagnostic only when the family enables it and there
is a qualifying suspicion signal, such as a recorded acquisition hint, contradictory
index/type metadata, or a missing/incompatible required boundary. These signals gate
diagnostic work; they do not prove body identity or replace the S6 target. Reuse the
boundary result when continuing normalization instead of adding a `stop_after` flag to
`normalize_document()`.

If the diagnostic tests for exhibit designators, it must exclude recognized TOC/index
spans before treating a match as body evidence. Verify the post-reflow character-span
coordinate contract before relying on that shield. `raw` remains the original source;
`render_to_txt` is a separate normalized result. An unsupported `render_to_xml` operation
does not block either output.

### Indexed exhibits

An indexed exhibit already has an S6 row/type and locator. It uses no primary cover
boundary. Text and HTML operations follow the generic file route; flat XML stays raw for
downstream consumers. An exhibit pack may run only when the expected code/authority has
registered coverage and the policy/capability enables it. Content assessment is
diagnostic-only and cannot trigger a new index request or slot change.

## Stored type and snapshot

Keep source fetches and operation outputs distinct:

| Stored concept | Contents |
|---|---|
| `StoredDocument` | Logical target identity, pinned operation policy, source records, operation results, and aggregate completeness. |
| `AcquiredSource` | One distinct HTTP/bundle body with locator, route, attempts, status, digest/size, and staged-body reference. Operations using identical source bytes share it. |
| `StoredRepresentation` | One operation result with operation ID, output kind, source reference(s), status, output digest/size, handler/version, and stored artifact reference. `raw` may alias its source. |

The snapshot records unsupported, unavailable, failed, and successful operation outcomes.
Do not merge `raw` and rendered results because they belong to one target or happen to
have the same digest. Content-addressed storage may share bytes while preserving each
operation/source reference and provenance.

Current S6 and S9 contracts model one target with one selected body. Multi-operation
processing requires versioned plan/work-order/run-state/handoff/receipt contracts and a
parent logical-document view. This is separate from the S5 inventory snapshot and does
not authorize S11 publication.

## Acceptance checks

- Explicit `[raw, render_to_txt, render_to_xml]` runs each supported operation and records
  unsupported ones as ignored without failing the other outputs.
- With no explicit policy, the first implemented operation wins in the stated priority;
  the capability/handler version is pinned.
- Operations sharing an input source fetch it once. XSL `render_to_xml` records a separate
  archive-root XML fetch, whose bytes remain opaque.
- HTML-only Form 4 remains processable as raw or text. An unimplemented translator is
  ignored and is never represented as an acquired XML file.
- Raw-only paths ignore render operations; PDF text runs only when supported; unknown
  routes remain explicit raw-only results.
- Primary reports run cover normalization only through a supported text operation;
  indexed exhibits never run a cover boundary.
- Snapshot completeness is operation-aware and preserves each output/source status; a
  successful `raw` result cannot hide a failed required rendered result.
- Acquisition does not fetch unplanned sources, parse XML, change S6 identity, or publish
  S11 artifacts.

## Existing contracts to reconcile

The current [S6 specification](../document_planning/specs.md) and
[S10 processing contract](../S10_processing.md) still describe single-body/raw-first
behavior. The separate [S6 acquisition-policy plan](../document_planning/acquisition_policy_plan.md)
proposes per-target operation sets, default operation priority, shared source inputs, and
separate stored operation results. Fold accepted behavior into the normative S6/S10 specs
and version their work-order, snapshot, and receipt contracts before implementation.
