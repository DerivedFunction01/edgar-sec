"""XBRL instance document parser extracting contexts, units, and atomic facts."""

from __future__ import annotations

from dataclasses import dataclass, field
import xml.etree.ElementTree as ET

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.parsing.xml_parser import (
    safe_parse_root,
    split_qname,
    strip_namespace,
)


@dataclass(slots=True)
class _ParsedContext:
    context_id: str
    period_type: str
    start_date: str | None = None
    end_date: str | None = None
    instant_date: str | None = None
    dimensions: dict[str, str] = field(default_factory=dict)


def _extract_contexts(root: ET.Element) -> dict[str, _ParsedContext]:
    contexts: dict[str, _ParsedContext] = {}
    for elem in root:
        if strip_namespace(elem.tag) != "context":
            continue
        cid = elem.attrib.get("id")
        if not cid:
            continue

        period_type = "duration"
        start_date: str | None = None
        end_date: str | None = None
        instant_date: str | None = None
        dims: dict[str, str] = {}

        for child in elem:
            tag = strip_namespace(child.tag)
            if tag == "period":
                for p_child in child:
                    ptag = strip_namespace(p_child.tag)
                    if ptag == "startDate":
                        start_date = (p_child.text or "").strip()
                    elif ptag == "endDate":
                        end_date = (p_child.text or "").strip()
                    elif ptag == "instant":
                        instant_date = (p_child.text or "").strip()
                        period_type = "instant"
            elif tag == "entity":
                for e_child in child:
                    if strip_namespace(e_child.tag) in ("segment", "scenario"):
                        for m in e_child:
                            mtag = strip_namespace(m.tag)
                            if mtag == "explicitMember":
                                dim = m.attrib.get("dimension", "")
                                val = (m.text or "").strip()
                                if dim and val:
                                    dims[dim] = val
                            elif mtag == "typedMember":
                                dim = m.attrib.get("dimension", "")
                                val = "".join(m.itertext()).strip()
                                if dim and val:
                                    dims[dim] = val

        contexts[cid] = _ParsedContext(
            context_id=cid,
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            instant_date=instant_date,
            dimensions=dims,
        )
    return contexts


def _find_measure_text(elem: ET.Element) -> str:
    for child in elem.iter():
        if strip_namespace(child.tag) == "measure":
            val = (child.text or "").strip()
            return val.split(":")[-1] if ":" in val else val
    return ""


def _extract_units(root: ET.Element) -> dict[str, str]:
    units: dict[str, str] = {}
    for elem in root:
        if strip_namespace(elem.tag) != "unit":
            continue
        uid = elem.attrib.get("id")
        if not uid:
            continue
        divide = next((c for c in elem if strip_namespace(c.tag) == "divide"), None)
        if divide is not None:
            num_elem = next(
                (c for c in divide if strip_namespace(c.tag) == "unitNumerator"), None
            )
            den_elem = next(
                (c for c in divide if strip_namespace(c.tag) == "unitDenominator"), None
            )
            num = _find_measure_text(num_elem) if num_elem is not None else ""
            den = _find_measure_text(den_elem) if den_elem is not None else ""
            if num and den:
                units[uid] = f"{num}/{den}"
                continue
            if num or den:
                units[uid] = num or den
                continue
        units[uid] = _find_measure_text(elem)
    return units


def _extract_namespace_map(xml_data: bytes | str) -> dict[str, str]:
    payload = xml_data.encode("utf-8") if isinstance(xml_data, str) else xml_data
    ns_map: dict[str, str] = {}
    import io

    try:
        for _, (prefix, uri) in ET.iterparse(io.BytesIO(payload), events=("start-ns",)):
            if prefix and uri and uri not in ns_map:
                ns_map[uri] = prefix
    except Exception:
        pass
    return ns_map


def _resolve_qname(tag: str, ns_map: dict[str, str]) -> str:
    ns, local = split_qname(tag)
    if not ns:
        if "_" in local and ":" not in local:
            pfx, _, n = local.partition("_")
            return f"{pfx}:{n}"
        return local

    if ns in ns_map:
        return f"{ns_map[ns]}:{local}"

    if "us-gaap" in ns:
        return f"us-gaap:{local}"
    if "dei" in ns:
        return f"dei:{local}"
    if "srt" in ns:
        return f"srt:{local}"

    token = ns.rstrip("/").split("/")[-1].split("#")[-1]
    return f"{token}:{local}"


def parse_instance_facts(
    xml_data: bytes | str,
    accession: AccessionNumber | str,
) -> tuple[XbrlFact, ...]:
    """Parse XBRL instance XML and extract typed facts mapped to contexts and units."""
    root = safe_parse_root(xml_data)
    ns_map = _extract_namespace_map(xml_data)
    acc = (
        accession
        if isinstance(accession, AccessionNumber)
        else AccessionNumber(accession)
    )

    contexts = _extract_contexts(root)
    units = _extract_units(root)
    facts: list[XbrlFact] = []

    for elem in root:
        local_tag = strip_namespace(elem.tag)
        if local_tag in (
            "context",
            "unit",
            "schemaRef",
            "linkbaseRef",
            "roleRef",
            "arcroleRef",
        ):
            continue

        cref = elem.attrib.get("contextRef")
        if not cref:
            continue

        raw_val = (elem.text or "").strip()
        val: float | str | None = None
        if raw_val:
            try:
                val = float(raw_val)
            except ValueError:
                val = raw_val

        dec_str = elem.attrib.get("decimals")
        decimals: int | None = None
        if dec_str is not None:
            try:
                decimals = int(dec_str)
            except ValueError:
                decimals = None

        qname = _resolve_qname(elem.tag, ns_map)

        uref = elem.attrib.get("unitRef")
        unit_str = units.get(uref or "") if uref else None

        ctx = contexts.get(cref)
        period_type = ctx.period_type if ctx else "duration"
        start_date = ctx.start_date if ctx else None
        end_date = ctx.end_date if ctx else None
        instant_date = ctx.instant_date if ctx else None
        dims = ctx.dimensions if ctx else {}

        facts.append(
            XbrlFact(
                accession=acc,
                concept_qname=qname,
                value=val,
                unit=unit_str,
                decimals=decimals,
                period_type=period_type,
                start_date=start_date,
                end_date=end_date,
                instant_date=instant_date,
                dimensions=dims,
                context_id=cref,
            )
        )

    return tuple(facts)
