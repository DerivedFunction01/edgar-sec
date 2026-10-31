"""Linkbase XML parsers extracting calculation, presentation, label, definition, and schema arcs."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    ConceptLabel,
    DefinitionArc,
    LinkbaseBundle,
    PresentationArc,
)
from edgar_sec.engine.xbrl.parsing.xml_parser import (
    resolve_href_qname,
    safe_parse_root,
    strip_namespace,
)

_XLINK_NS = "{http://www.w3.org/1999/xlink}"
_XBRLI_NS = "{http://www.xbrl.org/2003/instance}"
_XBRDT_NS = "{http://xbrl.org/2005/xbrldt}"


def _get_attr(elem: ET.Element, name: str) -> str | None:
    return elem.attrib.get(f"{_XLINK_NS}{name}") or elem.attrib.get(name)


def _get_xbrldt_attr(elem: ET.Element, name: str) -> str | None:
    return elem.attrib.get(f"{_XBRDT_NS}{name}") or elem.attrib.get(name)


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    return None


def parse_calculation_linkbase(
    xml_data: bytes | str,
) -> tuple[CalculationArc, ...]:
    """Parse calculation linkbase XML extracting weighted calculation arcs."""
    try:
        root = safe_parse_root(xml_data)
    except Exception:
        return ()
    arcs: list[CalculationArc] = []

    for link in root.iter():
        if strip_namespace(link.tag) != "calculationLink":
            continue
        role_uri = _get_attr(link, "role") or ""
        locators: dict[str, str] = {}
        link_arcs: list[ET.Element] = []

        for child in link:
            tag = strip_namespace(child.tag)
            if tag == "loc":
                label = _get_attr(child, "label")
                href = _get_attr(child, "href")
                if label and href:
                    locators[label] = resolve_href_qname(href)
            elif tag == "calculationArc":
                link_arcs.append(child)

        for arc in link_arcs:
            from_lbl = _get_attr(arc, "from")
            to_lbl = _get_attr(arc, "to")
            weight_str = arc.attrib.get("weight", "1")
            order_str = arc.attrib.get("order")
            if not from_lbl or not to_lbl:
                continue

            parent = locators.get(from_lbl, from_lbl)
            child_qname = locators.get(to_lbl, to_lbl)
            try:
                weight = float(weight_str)
            except ValueError:
                weight = 1.0
            order = float(order_str) if order_str is not None else None

            arcs.append(
                CalculationArc(
                    parent_qname=parent,
                    child_qname=child_qname,
                    weight=weight,
                    order=order,
                    role_uri=role_uri,
                )
            )

    return tuple(arcs)


def parse_presentation_linkbase(
    xml_data: bytes | str,
) -> tuple[PresentationArc, ...]:
    """Parse presentation linkbase XML extracting hierarchical presentation arcs."""
    try:
        root = safe_parse_root(xml_data)
    except Exception:
        return ()
    arcs: list[PresentationArc] = []

    for link in root.iter():
        if strip_namespace(link.tag) != "presentationLink":
            continue
        role_uri = _get_attr(link, "role") or ""
        locators: dict[str, str] = {}
        link_arcs: list[ET.Element] = []

        for child in link:
            tag = strip_namespace(child.tag)
            if tag == "loc":
                label = _get_attr(child, "label")
                href = _get_attr(child, "href")
                if label and href:
                    locators[label] = resolve_href_qname(href)
            elif tag == "presentationArc":
                link_arcs.append(child)

        for arc in link_arcs:
            from_lbl = _get_attr(arc, "from")
            to_lbl = _get_attr(arc, "to")
            order_str = arc.attrib.get("order")
            if not from_lbl or not to_lbl:
                continue

            parent = locators.get(from_lbl, from_lbl)
            child_qname = locators.get(to_lbl, to_lbl)
            order = float(order_str) if order_str is not None else None

            arcs.append(
                PresentationArc(
                    parent_qname=parent,
                    child_qname=child_qname,
                    order=order,
                    role_uri=role_uri,
                )
            )

    return tuple(arcs)


def parse_definition_linkbase(
    xml_data: bytes | str,
) -> tuple[DefinitionArc, ...]:
    """Parse definition linkbase XML extracting dimensional definition arcs."""
    try:
        root = safe_parse_root(xml_data)
    except Exception:
        return ()
    arcs: list[DefinitionArc] = []

    for link in root.iter():
        if strip_namespace(link.tag) != "definitionLink":
            continue
        role_uri = _get_attr(link, "role") or ""
        locators: dict[str, str] = {}
        link_arcs: list[ET.Element] = []

        for child in link:
            tag = strip_namespace(child.tag)
            if tag == "loc":
                label = _get_attr(child, "label")
                href = _get_attr(child, "href")
                if label and href:
                    locators[label] = resolve_href_qname(href)
            elif tag == "definitionArc":
                link_arcs.append(child)

        for arc in link_arcs:
            from_lbl = _get_attr(arc, "from")
            to_lbl = _get_attr(arc, "to")
            arcrole = _get_attr(arc, "arcrole") or ""
            order_str = arc.attrib.get("order")
            if not from_lbl or not to_lbl:
                continue

            parent = locators.get(from_lbl, from_lbl)
            child_qname = locators.get(to_lbl, to_lbl)
            order = float(order_str) if order_str is not None else None

            arcs.append(
                DefinitionArc(
                    parent_qname=parent,
                    child_qname=child_qname,
                    arcrole=arcrole,
                    order=order,
                    role_uri=role_uri,
                    usable=_parse_bool(_get_xbrldt_attr(arc, "usable")),
                    closed=_parse_bool(_get_xbrldt_attr(arc, "closed")),
                    context_element=_get_xbrldt_attr(arc, "contextElement"),
                    target_role=_get_xbrldt_attr(arc, "targetRole"),
                )
            )

    return tuple(arcs)


def parse_label_linkbase(xml_data: bytes | str) -> tuple[ConceptLabel, ...]:
    """Parse label linkbase XML extracting human-readable concept descriptions."""
    try:
        root = safe_parse_root(xml_data)
    except Exception:
        return ()
    locators: dict[str, str] = {}
    label_resources: dict[str, tuple[str, str, str]] = {}
    label_arcs: list[tuple[str, str]] = []

    for link in root.iter():
        if strip_namespace(link.tag) != "labelLink":
            continue
        for child in link:
            tag = strip_namespace(child.tag)
            lbl = _get_attr(child, "label")
            if tag == "loc" and lbl:
                href = _get_attr(child, "href")
                if href:
                    locators[lbl] = resolve_href_qname(href)
            elif tag == "label" and lbl:
                role = _get_attr(child, "role") or "http://www.xbrl.org/2003/role/label"
                lang = (
                    child.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
                    or "en-US"
                )
                text = (child.text or "").strip()
                label_resources[lbl] = (role, text, lang)
            elif tag == "labelArc":
                from_lbl = _get_attr(child, "from")
                to_lbl = _get_attr(child, "to")
                if from_lbl and to_lbl:
                    label_arcs.append((from_lbl, to_lbl))

    results: list[ConceptLabel] = []
    for from_lbl, to_lbl in label_arcs:
        concept = locators.get(from_lbl)
        res = label_resources.get(to_lbl)
        if concept and res:
            role, text, lang = res
            results.append(
                ConceptLabel(
                    concept_qname=concept, role_uri=role, label=text, lang=lang
                )
            )

    return tuple(results)


def parse_schema_declarations(
    xsd_data: bytes | str,
    target_prefix: str | None = None,
) -> tuple[ConceptDeclaration, ...]:
    """Parse taxonomy schema (.xsd) element definitions into concept declarations."""
    try:
        root = safe_parse_root(xsd_data)
    except Exception:
        return ()
    tns = root.attrib.get("targetNamespace", "")
    prefix = target_prefix or (tns.split("/")[-1] if "/" in tns else "ext")

    declarations: list[ConceptDeclaration] = []
    for elem in root:
        if strip_namespace(elem.tag) != "element":
            continue
        name = elem.attrib.get("name")
        if not name:
            continue
        period_type = elem.attrib.get(f"{_XBRLI_NS}periodType") or elem.attrib.get(
            "periodType"
        )
        balance = elem.attrib.get(f"{_XBRLI_NS}balance") or elem.attrib.get("balance")
        substitution_group = elem.attrib.get("substitutionGroup")
        item_type = elem.attrib.get("type")
        abstract = elem.attrib.get("abstract") == "true"
        qname = f"{prefix}:{name}"

        declarations.append(
            ConceptDeclaration(
                concept_qname=qname,
                name=name,
                period_type=period_type,
                balance=balance,
                substitution_group=substitution_group,
                item_type=item_type,
                abstract=abstract,
            )
        )

    return tuple(declarations)


def parse_linkbase_bundle(
    *,
    cal_xml: bytes | str | None = None,
    pre_xml: bytes | str | None = None,
    lab_xml: bytes | str | None = None,
    def_xml: bytes | str | None = None,
    xsd: bytes | str | None = None,
) -> LinkbaseBundle:
    """Build unified LinkbaseBundle from optional XML components."""
    cal_source = cal_xml if cal_xml else xsd
    pre_source = pre_xml if pre_xml else xsd
    lab_source = lab_xml if lab_xml else xsd
    def_source = def_xml if def_xml else xsd
    cal_arcs = parse_calculation_linkbase(cal_source) if cal_source else ()
    pre_arcs = parse_presentation_linkbase(pre_source) if pre_source else ()
    labels = parse_label_linkbase(lab_source) if lab_source else ()
    def_arcs = parse_definition_linkbase(def_source) if def_source else ()
    decls = parse_schema_declarations(xsd) if xsd else ()
    return LinkbaseBundle(
        calculation_arcs=cal_arcs,
        presentation_arcs=pre_arcs,
        labels=labels,
        declarations=decls,
        definition_arcs=def_arcs,
    )
