# `edgar_sec/domain/world/` — Currency and geography substrate

The one declared standing for world knowledge the engine consumes:
currency records and the disclosure-geography hierarchy.

## Purpose

Currency facts and geography facts were previously re-declared per
consumer — a currency table inside the tables engine, a geography
DAG file inside the XBRL taxonomy, partial copies in the forms
engine — and the copies had drifted (different code sets, an empty
suffix set against a fuller union standing, symbol sets re-derived
in the numeric grammar). This package declares each fact once, as
immutable data with pure resolution functions, and every consumer
derives its own sets from the records.

## Contracts

- **Data as literals**: records are immutable Python literals in
  the package (frozen dataclasses, `MappingProxyType` mappings).
  Layer 1 performs no I/O; nothing here reads a file, an
  environment, or a clock.
- **Facts only**: the substrate states what a currency is called,
  which symbols it claims, whether a symbol binds prefix or
  suffix, and how places contain each other. It never decides a
  consumer's verdict — numeric mechanics, XBRL unit classes and
  axes, FX tag content, segment geographic content, and filer
  geography stay distinct consumers over the same records.
- **Ambiguity is data**: a symbol or name claimed by more than one
  currency (the symbol `kr`, claimed by SEK and DKK) resolves to
  all its owners; no consumer may silently pick one.
- **Attestation-gated growth**: a currency code or place stands
  here when a production consumer or a tree dataset names it;
  un-attested standings from outside programmes wait outside.

## Layout

- `currencies.py` — currency records and their derived standings.
- `geography_edges.py` — the hierarchy's meronymy edges as data.
- `geography_places.py` — country and region records for the nodes.
- `geography.py` — pure resolution over the records (lookup,
  ancestors, containment, domicile-relative status, place terms).

## Decisions priced at adoption

- **Code set (18)**: the tables grammar's 17 codes plus DKK — the
  only wider-standing code attested in this tree's own data (an
  industries profile names it as a functional currency while no
  currency standing carried it). The union's other codes (NOK,
  AED, THB, PLN, CZK, HUF, RON, ARS, IDR, RUB, SAR, TRY, NZD) are
  attestation-gated extensions, adopted when a consumer or a
  corpus names them.
- **Prefix/suffix**: the tables standing the production numeric
  grammar is wired to — every adopted currency prefix, the suffix
  set empty. The union's suffix claims (INR, SEK among them)
  contradict that wired standing; the record keeps the flags so a
  priced adoption is a data change, not a schema change.
- **Ambiguity**: the symbol `kr` is claimed by SEK and DKK and
  resolves to both; ambiguous names are declared on the records.

## Package conventions

Stdlib-only imports; frozen, slotted dataclass records; mappings
exposed as `MappingProxyType`; derived sets computed once at
import; consumers import the submodule directly
(`edgar_sec.domain.world.currencies`), never a barrel re-export.

## Deliberate gaps

- GDP/population weights, labor rates, tax-haven penalties, and
  the city gazetteer are consumer inference, not world facts, and
  do not stand here.
- The hierarchy is disclosure geography, not a domicile registry:
  domicile codes with no DAG country node (CW, CY, IE, JE, LR, MC,
  PA, UY) resolve to no node rather than to an invented one.
- The currency code set is the attested set (`CURRENCIES` in
  `currencies.py`), not the full ISO list and not the union
  programme's wider declaration; extension is attestation-gated.
