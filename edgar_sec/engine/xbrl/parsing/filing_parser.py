"""Filing aggregate XBRL extractor orchestrating linkbase and instance parsers."""

from __future__ import annotations

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import Cik
from edgar_sec.engine.xbrl.discovery.discovery import LinkbaseType, classify_linkbase
from edgar_sec.engine.xbrl.parsing.instance_parser import (
    extract_prefix_namespaces,
    parse_instance_facts,
)
from edgar_sec.engine.xbrl.parsing.linkbase_parser import parse_linkbase_bundle
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact
from edgar_sec.engine.xbrl.taxonomy.archive import table_for_namespaces


def _parse_candidate(
    ins_bytes: bytes,
    filing: FilingAggregate,
    bundle: LinkbaseBundle,
) -> tuple[tuple[XbrlFact, ...], dict[str, str]]:
    """Parse one instance candidate: its facts and prefix namespaces."""
    prefix_namespaces = extract_prefix_namespaces(ins_bytes)
    item_types = table_for_namespaces(prefix_namespaces)
    for declaration in bundle.declarations:
        if declaration.item_type is not None:
            item_types[declaration.concept_qname] = declaration.item_type
    facts = parse_instance_facts(ins_bytes, filing.accession, item_types)
    return facts, prefix_namespaces


def _select_instance(
    candidates: list[tuple[bytes, str | None]],
    filing: FilingAggregate,
    bundle: LinkbaseBundle,
) -> tuple[tuple[XbrlFact, ...], dict[str, str], str | None]:
    """Select the instance the filing's linkbases describe, by role.

    A fee exhibit beside a main instance loses to the described one;
    position never decides.
    """
    if not candidates:
        return (), {}, None
    if len(candidates) == 1:
        ins_bytes, ins_filename = candidates[0]
        facts, namespaces = _parse_candidate(ins_bytes, filing, bundle)
        return facts, namespaces, ins_filename
    described = (
        {arc.parent_qname for arc in bundle.calculation_arcs}
        | {arc.child_qname for arc in bundle.calculation_arcs}
        | {arc.parent_qname for arc in bundle.presentation_arcs}
        | {arc.child_qname for arc in bundle.presentation_arcs}
        | {declaration.concept_qname for declaration in bundle.declarations}
    )
    best: tuple[tuple[int, int], tuple[XbrlFact, ...], dict[str, str], str | None] = (
        (-1, -1),
        (),
        {},
        None,
    )
    for ins_bytes, ins_filename in candidates:
        facts, namespaces = _parse_candidate(ins_bytes, filing, bundle)
        overlap = len({fact.concept_qname for fact in facts} & described)
        score = (overlap, len(facts))
        if score > best[0]:
            best = (score, facts, namespaces, ins_filename)
    return best[1], best[2], best[3]


def parse_filing_xbrl(filing: FilingAggregate) -> FilingXbrl:
    """Extract and parse all discovered XBRL linkbases and instance facts for a filing."""
    cal_bytes: bytes | None = None
    pre_bytes: bytes | None = None
    lab_bytes: bytes | None = None
    def_bytes: bytes | None = None
    xsd_bytes: bytes | None = None
    instances: list[tuple[bytes, str | None]] = []

    for att in filing.linkbases:
        lb_type = classify_linkbase(
            att.document_type or "",
            att.filename or "",
            att.description or "",
        )
        if lb_type is None:
            continue
        if lb_type == LinkbaseType.CALCULATION:
            cal_bytes = att.raw()
        elif lb_type == LinkbaseType.PRESENTATION:
            pre_bytes = att.raw()
        elif lb_type == LinkbaseType.LABEL:
            lab_bytes = att.raw()
        elif lb_type == LinkbaseType.DEFINITION:
            def_bytes = att.raw()
        elif lb_type == LinkbaseType.SCHEMA:
            xsd_bytes = att.raw()
        elif lb_type == LinkbaseType.INSTANCE:
            payload = att.raw()
            if payload is not None:
                instances.append((payload, att.filename))

    bundle = parse_linkbase_bundle(
        cal_xml=cal_bytes,
        pre_xml=pre_bytes,
        lab_xml=lab_bytes,
        def_xml=def_bytes,
        xsd=xsd_bytes,
    )
    facts, prefix_namespaces, ins_filename = _select_instance(instances, filing, bundle)
    primary_cik = filing.ciks[0] if filing.ciks else Cik.from_raw(0)
    namespaces = tuple(sorted(prefix_namespaces.items()))

    return FilingXbrl(
        accession=filing.accession,
        cik=primary_cik,
        facts=facts,
        linkbases=bundle,
        namespaces=namespaces,
        instance_document=ins_filename,
    )
