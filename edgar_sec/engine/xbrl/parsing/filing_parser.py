"""Filing aggregate XBRL extractor orchestrating linkbase and instance parsers."""

from __future__ import annotations

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import Cik
from edgar_sec.engine.xbrl.discovery.discovery import LinkbaseType, classify_linkbase
from edgar_sec.engine.xbrl.parsing.instance_parser import parse_instance_facts
from edgar_sec.engine.xbrl.parsing.linkbase_parser import parse_linkbase_bundle
from edgar_sec.engine.xbrl.schema.models import FilingXbrl


def parse_filing_xbrl(filing: FilingAggregate) -> FilingXbrl:
    """Extract and parse all discovered XBRL linkbases and instance facts for a filing."""
    cal_bytes: bytes | None = None
    pre_bytes: bytes | None = None
    lab_bytes: bytes | None = None
    xsd_bytes: bytes | None = None
    ins_bytes: bytes | None = None

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
        elif lb_type == LinkbaseType.SCHEMA:
            xsd_bytes = att.raw()
        elif lb_type == LinkbaseType.INSTANCE:
            ins_bytes = att.raw()

    bundle = parse_linkbase_bundle(
        cal_xml=cal_bytes,
        pre_xml=pre_bytes,
        lab_xml=lab_bytes,
        xsd=xsd_bytes,
    )
    facts = parse_instance_facts(ins_bytes, filing.accession) if ins_bytes else ()
    primary_cik = filing.ciks[0] if filing.ciks else Cik.from_raw(0)

    return FilingXbrl(
        accession=filing.accession,
        cik=primary_cik,
        facts=facts,
        linkbases=bundle,
    )
