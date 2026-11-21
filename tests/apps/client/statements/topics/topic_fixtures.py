from __future__ import annotations

from edgar_sec.apps.client.core.facts import build_display_records
from edgar_sec.apps.client.statements.topics import build_segment_breakdown
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import DefinitionArc, XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

_ACC = AccessionNumber("0000000000-25-000001")


def _fact(qname: str, value: float, **kw: object) -> XbrlFact:
    return XbrlFact(_ACC, qname, value, unit="USD", **kw)  # type: ignore[arg-type]


def _instant(qname: str, value: float, day: str) -> XbrlFact:
    return _fact(qname, value, period_type="instant", instant_date=day)


def _duration(qname: str, value: float) -> XbrlFact:
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )


_REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
_BIZ_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
_GEO_AXIS = "srt:StatementGeographicalAxis"


def _segment_fact(
    qname: str, value: float, dimensions: dict[str, str] | None = None, **kw: object
) -> XbrlFact:
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions=dimensions or {},
        **kw,  # type: ignore[arg-type]
    )


def _build_segments(facts: list[XbrlFact], **kw: object):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_segment_breakdown(facts, records, taxonomy, **kw)  # type: ignore[arg-type]


_L3 = "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisAsset"
_L3_VALUE = _L3 + "Value"
_L3_AXIS = "us-gaap:FairValueByAssetClassAxis"
_L3_MEMBER = "x:CorpMember"


def _level3_fact(
    qname: str,
    value: float,
    dimensions: dict[str, str] | None = None,
    instant: str | None = None,
) -> XbrlFact:
    dims = {_L3_AXIS: _L3_MEMBER} if dimensions is None else dimensions
    if instant is not None:
        return _fact(
            qname, value, period_type="instant", instant_date=instant, dimensions=dims
        )
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions=dims,
    )


_DIM_DOMAIN = "http://xbrl.org/int/dim/arcrole/dimension-domain"
_DIM_DEFAULT = "http://xbrl.org/int/dim/arcrole/dimension-default"
_DOMAIN_MEMBER = "http://xbrl.org/int/dim/arcrole/domain-member"
_EQ_DOMAIN = "us-gaap:EquityComponentDomain"
_EQ_PARENT = "us-gaap:ParentMember"


def _def_arcs(
    axis: str, domain: str, edges: list[tuple[str, str]]
) -> tuple[DefinitionArc, ...]:
    arcs = [
        DefinitionArc(axis, domain, _DIM_DOMAIN),
        DefinitionArc(axis, domain, _DIM_DEFAULT),
    ]
    arcs.extend(DefinitionArc(parent, child, _DOMAIN_MEMBER) for parent, child in edges)
    return tuple(arcs)
