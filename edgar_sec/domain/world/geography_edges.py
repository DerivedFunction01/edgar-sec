"""Geography hierarchy edges: the meronymy DAG as data.

The disclosure-geography hierarchy stands here once: 94 edges,
73 nodes, 18 decomposition schemes. Every edge in this DAG is a
meronymy part-of relation; the notes carry the grouping rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class GeoEdge:
    """One meronymy edge: child is part of parent under a scheme."""

    child: str
    parent: str
    scheme: str = "PART_WHOLE"
    relation: str = "MERONYM"
    notes: str = ""


_EDGE_ROWS: tuple[tuple[str, str, str], ...] = (
    ("country:EG", "srt:AfricaMember", "D_GEO_AFRICA"),
    ("country:NG", "srt:AfricaMember", "D_GEO_AFRICA"),
    ("country:ZA", "srt:AfricaMember", "D_GEO_AFRICA"),
    ("srt:LatinAmericaMember", "srt:AmericasMember", "D_GEO_AMER"),
    ("srt:NorthAmericaMember", "srt:AmericasMember", "D_GEO_AMER"),
    ("country:AU", "corp:ANZMember", "D_GEO_ANZ"),
    ("country:NZ", "corp:ANZMember", "D_GEO_ANZ"),
    ("corp:ANZMember", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("corp:ASEANMember", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:AU", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:CN", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:ID", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:IN", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:JP", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:KR", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:NZ", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:SG", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:VN", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("country:ID", "corp:ASEANMember", "D_GEO_ASEAN"),
    ("country:MY", "corp:ASEANMember", "D_GEO_ASEAN"),
    ("country:PH", "corp:ASEANMember", "D_GEO_ASEAN"),
    ("country:SG", "corp:ASEANMember", "D_GEO_ASEAN"),
    ("country:TH", "corp:ASEANMember", "D_GEO_ASEAN"),
    ("country:VN", "corp:ASEANMember", "D_GEO_ASEAN"),
    ("country:BE", "corp:BeneluxMember", "D_GEO_BENELUX"),
    ("country:LU", "corp:BeneluxMember", "D_GEO_BENELUX"),
    ("country:NL", "corp:BeneluxMember", "D_GEO_BENELUX"),
    ("country:BG", "corp:CEEMember", "D_GEO_CEE"),
    ("country:CZ", "corp:CEEMember", "D_GEO_CEE"),
    ("country:HU", "corp:CEEMember", "D_GEO_CEE"),
    ("country:PL", "corp:CEEMember", "D_GEO_CEE"),
    ("country:RO", "corp:CEEMember", "D_GEO_CEE"),
    ("country:SK", "corp:CEEMember", "D_GEO_CEE"),
    ("country:AR", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("country:BR", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("country:CL", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("country:CO", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("country:MX", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("country:PE", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("srt:CaribbeanMember", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("srt:CentralAmericaMember", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("country:AT", "corp:DACHMember", "D_GEO_DACH"),
    ("country:CH", "corp:DACHMember", "D_GEO_DACH"),
    ("country:DE", "corp:DACHMember", "D_GEO_DACH"),
    ("corp:MENAMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("srt:AfricaMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("srt:EuropeMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("srt:EuropeanUnionMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("srt:MiddleEastMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("corp:BeneluxMember", "srt:EuropeMember", "D_GEO_EUROPE"),
    ("corp:CEEMember", "srt:EuropeMember", "D_GEO_EUROPE"),
    ("corp:DACHMember", "srt:EuropeMember", "D_GEO_EUROPE"),
    ("corp:NordicsMember", "srt:EuropeMember", "D_GEO_EUROPE"),
    ("country:CH", "srt:EuropeMember", "D_GEO_EUROPE"),
    ("country:GB", "srt:EuropeMember", "D_GEO_EUROPE"),
    ("srt:EuropeanUnionMember", "srt:EuropeMember", "D_GEO_EUROPE"),
    ("country:DE", "srt:EuropeanUnionMember", "D_GEO_EUROPE"),
    ("country:ES", "srt:EuropeanUnionMember", "D_GEO_EUROPE"),
    ("country:FR", "srt:EuropeanUnionMember", "D_GEO_EUROPE"),
    ("country:IT", "srt:EuropeanUnionMember", "D_GEO_EUROPE"),
    ("country:NL", "srt:EuropeanUnionMember", "D_GEO_EUROPE"),
    ("srt:AmericasMember", "srt:SegmentGeographicalDomain", "D_GEO_GLOBAL"),
    ("srt:AsiaPacificMember", "srt:SegmentGeographicalDomain", "D_GEO_GLOBAL"),
    ("srt:EMEAMember", "srt:SegmentGeographicalDomain", "D_GEO_GLOBAL"),
    ("country:AE", "corp:MENAMember", "D_GEO_MENA"),
    ("country:EG", "corp:MENAMember", "D_GEO_MENA"),
    ("country:IL", "corp:MENAMember", "D_GEO_MENA"),
    ("country:MA", "corp:MENAMember", "D_GEO_MENA"),
    ("country:QA", "corp:MENAMember", "D_GEO_MENA"),
    ("country:SA", "corp:MENAMember", "D_GEO_MENA"),
    ("srt:MiddleEastMember", "corp:MENAMember", "D_GEO_MENA"),
    ("country:AE", "srt:MiddleEastMember", "D_GEO_MIDDLE_EAST"),
    ("country:IL", "srt:MiddleEastMember", "D_GEO_MIDDLE_EAST"),
    ("country:SA", "srt:MiddleEastMember", "D_GEO_MIDDLE_EAST"),
    ("country:DK", "corp:NordicsMember", "D_GEO_NORDICS"),
    ("country:FI", "corp:NordicsMember", "D_GEO_NORDICS"),
    ("country:IS", "corp:NordicsMember", "D_GEO_NORDICS"),
    ("country:NO", "corp:NordicsMember", "D_GEO_NORDICS"),
    ("country:SE", "corp:NordicsMember", "D_GEO_NORDICS"),
    ("country:CA", "srt:NorthAmericaMember", "D_GEO_NORTH_AMER"),
    ("country:US", "srt:NorthAmericaMember", "D_GEO_NORTH_AMER"),
    ("country:MX", "srt:NorthAmericaMember", "D_GEO_USMCA"),
    ("country:US", "srt:NorthAmericaMember", "D_GEO_USMCA"),
    ("country:CA", "srt:NorthAmericaMember", "D_GEO_USMCA"),
    ("country:CN", "corp:GreaterChinaMember", "D_GEO_GREATER_CHINA"),
    ("country:HK", "corp:GreaterChinaMember", "D_GEO_GREATER_CHINA"),
    ("country:TW", "corp:GreaterChinaMember", "D_GEO_GREATER_CHINA"),
    ("country:MO", "corp:GreaterChinaMember", "D_GEO_GREATER_CHINA"),
    ("corp:GreaterChinaMember", "srt:AsiaPacificMember", "D_GEO_APAC"),
    ("srt:EuropeMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("srt:MiddleEastMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("srt:AfricaMember", "srt:EMEAMember", "D_GEO_EMEA"),
    ("srt:CentralAmericaMember", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
    ("srt:SouthAmericaMember", "srt:LatinAmericaMember", "D_GEO_CORP_LATAM"),
)

_EDGE_NOTES: MappingProxyType[tuple[str, str, str], str] = MappingProxyType(
    {
        (
            "country:EG",
            "srt:AfricaMember",
            "D_GEO_AFRICA",
        ): "Egypt is a sub-region of Africa (often grouped in MENA)",
        (
            "country:NG",
            "srt:AfricaMember",
            "D_GEO_AFRICA",
        ): "Nigeria is a sub-region of Africa",
        (
            "country:ZA",
            "srt:AfricaMember",
            "D_GEO_AFRICA",
        ): "South Africa is a sub-region of Africa",
        (
            "srt:LatinAmericaMember",
            "srt:AmericasMember",
            "D_GEO_AMER",
        ): "Latin America is a sub-region of the Americas",
        (
            "srt:NorthAmericaMember",
            "srt:AmericasMember",
            "D_GEO_AMER",
        ): "North America is a sub-region of the Americas",
        (
            "country:AU",
            "corp:ANZMember",
            "D_GEO_ANZ",
        ): "Australia is a constituent of the ANZ commercial cluster",
        (
            "country:NZ",
            "corp:ANZMember",
            "D_GEO_ANZ",
        ): "New Zealand is a constituent of the ANZ commercial cluster",
        (
            "corp:ANZMember",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "ANZ commercial cluster rolls up into Asia-Pacific",
        (
            "corp:ASEANMember",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "ASEAN trading bloc is a sub-region of Asia-Pacific",
        (
            "country:AU",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "Australia is a sub-region of Asia-Pacific / Australasia",
        (
            "country:CN",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "Greater China is a sub-region of Asia-Pacific",
        (
            "country:ID",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "Indonesia is a sub-region of Asia-Pacific / ASEAN",
        (
            "country:IN",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "India is a sub-region of Asia-Pacific",
        (
            "country:JP",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "Japan is a sub-region of Asia-Pacific (KO)",
        (
            "country:KR",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "South Korea is a sub-region of Asia-Pacific",
        (
            "country:NZ",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "New Zealand is a sub-region of Asia-Pacific / Australasia",
        (
            "country:SG",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "Singapore is a sub-region of Asia-Pacific / ASEAN",
        (
            "country:VN",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "Vietnam is a sub-region of Asia-Pacific / ASEAN",
        (
            "country:ID",
            "corp:ASEANMember",
            "D_GEO_ASEAN",
        ): "Indonesia is a member state of ASEAN",
        (
            "country:MY",
            "corp:ASEANMember",
            "D_GEO_ASEAN",
        ): "Malaysia is a member state of ASEAN",
        (
            "country:PH",
            "corp:ASEANMember",
            "D_GEO_ASEAN",
        ): "Philippines is a member state of ASEAN",
        (
            "country:SG",
            "corp:ASEANMember",
            "D_GEO_ASEAN",
        ): "Singapore is a member state of ASEAN",
        (
            "country:TH",
            "corp:ASEANMember",
            "D_GEO_ASEAN",
        ): "Thailand is a member state of ASEAN",
        (
            "country:VN",
            "corp:ASEANMember",
            "D_GEO_ASEAN",
        ): "Vietnam is a member state of ASEAN",
        (
            "country:BE",
            "corp:BeneluxMember",
            "D_GEO_BENELUX",
        ): "Belgium is a constituent member of Benelux",
        (
            "country:LU",
            "corp:BeneluxMember",
            "D_GEO_BENELUX",
        ): "Luxembourg is a constituent member of Benelux",
        (
            "country:NL",
            "corp:BeneluxMember",
            "D_GEO_BENELUX",
        ): "Netherlands is a constituent member of Benelux",
        ("country:BG", "corp:CEEMember", "D_GEO_CEE"): "Bulgaria is a core CEE market",
        (
            "country:CZ",
            "corp:CEEMember",
            "D_GEO_CEE",
        ): "Czech Republic is a core CEE market",
        ("country:HU", "corp:CEEMember", "D_GEO_CEE"): "Hungary is a core CEE market",
        ("country:PL", "corp:CEEMember", "D_GEO_CEE"): "Poland is a core CEE market",
        ("country:RO", "corp:CEEMember", "D_GEO_CEE"): "Romania is a core CEE market",
        ("country:SK", "corp:CEEMember", "D_GEO_CEE"): "Slovakia is a core CEE market",
        (
            "country:AR",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Argentina is a sub-region of Latin America",
        (
            "country:BR",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Brazil is a sub-region of Latin America (PEP)",
        (
            "country:CL",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Chile is a sub-region of Latin America",
        (
            "country:CO",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Colombia is a sub-region of Latin America",
        (
            "country:MX",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Mexico is a sub-region of Latin America in corporate LatAm reporting (KO, PEP)",
        (
            "country:PE",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Peru is a sub-region of Latin America",
        (
            "srt:CaribbeanMember",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Caribbean is a sub-region of Latin America/Americas",
        (
            "srt:CentralAmericaMember",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Central America is a sub-region of Latin America",
        (
            "country:AT",
            "corp:DACHMember",
            "D_GEO_DACH",
        ): "Austria (A) is a constituent of the DACH corporate cluster",
        (
            "country:CH",
            "corp:DACHMember",
            "D_GEO_DACH",
        ): "Switzerland (CH) is a constituent of the DACH corporate cluster",
        (
            "country:DE",
            "corp:DACHMember",
            "D_GEO_DACH",
        ): "Germany (D) is a constituent of the DACH corporate cluster",
        (
            "corp:MENAMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "MENA corporate reporting unit rolls up into EMEA",
        (
            "srt:AfricaMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "Africa is a sub-region of EMEA",
        (
            "srt:EuropeMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "Europe is a sub-region of EMEA",
        (
            "srt:EuropeanUnionMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "EU is a sub-region of EMEA (KO)",
        (
            "srt:MiddleEastMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "Middle East is a sub-region of EMEA",
        (
            "corp:BeneluxMember",
            "srt:EuropeMember",
            "D_GEO_EUROPE",
        ): "Benelux economic union is a sub-region of Europe",
        (
            "corp:CEEMember",
            "srt:EuropeMember",
            "D_GEO_EUROPE",
        ): "Central & Eastern Europe cluster rolls up into Europe",
        (
            "corp:DACHMember",
            "srt:EuropeMember",
            "D_GEO_EUROPE",
        ): "DACH commercial cluster is a sub-region of Europe",
        (
            "corp:NordicsMember",
            "srt:EuropeMember",
            "D_GEO_EUROPE",
        ): "Nordics commercial cluster rolls up into Europe",
        (
            "country:CH",
            "srt:EuropeMember",
            "D_GEO_EUROPE",
        ): "Switzerland is a non-EU European market",
        (
            "country:GB",
            "srt:EuropeMember",
            "D_GEO_EUROPE",
        ): "United Kingdom is a sub-region of Europe",
        (
            "srt:EuropeanUnionMember",
            "srt:EuropeMember",
            "D_GEO_EUROPE",
        ): "EU is a proper subset of geographic Europe",
        (
            "country:DE",
            "srt:EuropeanUnionMember",
            "D_GEO_EUROPE",
        ): "Germany is a member state of the European Union",
        (
            "country:ES",
            "srt:EuropeanUnionMember",
            "D_GEO_EUROPE",
        ): "Spain is a member state of the European Union",
        (
            "country:FR",
            "srt:EuropeanUnionMember",
            "D_GEO_EUROPE",
        ): "France is a member state of the European Union",
        (
            "country:IT",
            "srt:EuropeanUnionMember",
            "D_GEO_EUROPE",
        ): "Italy is a member state of the European Union",
        (
            "country:NL",
            "srt:EuropeanUnionMember",
            "D_GEO_EUROPE",
        ): "Netherlands is a member state of the European Union",
        (
            "srt:AmericasMember",
            "srt:SegmentGeographicalDomain",
            "D_GEO_GLOBAL",
        ): "Americas roll up into global corporate reporting",
        (
            "srt:AsiaPacificMember",
            "srt:SegmentGeographicalDomain",
            "D_GEO_GLOBAL",
        ): "APAC rolls up into global corporate reporting",
        (
            "srt:EMEAMember",
            "srt:SegmentGeographicalDomain",
            "D_GEO_GLOBAL",
        ): "EMEA rolls up into global corporate reporting",
        (
            "country:AE",
            "corp:MENAMember",
            "D_GEO_MENA",
        ): "United Arab Emirates is a core market in MENA",
        (
            "country:EG",
            "corp:MENAMember",
            "D_GEO_MENA",
        ): "Egypt connects North Africa into MENA corporate reporting",
        (
            "country:IL",
            "corp:MENAMember",
            "D_GEO_MENA",
        ): "Israel is frequently grouped in MENA/EMEA",
        (
            "country:MA",
            "corp:MENAMember",
            "D_GEO_MENA",
        ): "Morocco is part of the North African component of MENA",
        (
            "country:QA",
            "corp:MENAMember",
            "D_GEO_MENA",
        ): "Qatar is part of the Middle East component of MENA",
        (
            "country:SA",
            "corp:MENAMember",
            "D_GEO_MENA",
        ): "Saudi Arabia is a core market in MENA",
        (
            "srt:MiddleEastMember",
            "corp:MENAMember",
            "D_GEO_MENA",
        ): "Middle East region rolls up into corporate MENA",
        (
            "country:AE",
            "srt:MiddleEastMember",
            "D_GEO_MIDDLE_EAST",
        ): "United Arab Emirates is a sub-region of the Middle East",
        (
            "country:IL",
            "srt:MiddleEastMember",
            "D_GEO_MIDDLE_EAST",
        ): "Israel is a sub-region of the Middle East",
        (
            "country:SA",
            "srt:MiddleEastMember",
            "D_GEO_MIDDLE_EAST",
        ): "Saudi Arabia is a sub-region of the Middle East",
        (
            "country:DK",
            "corp:NordicsMember",
            "D_GEO_NORDICS",
        ): "Denmark is a constituent market of the Nordic region",
        (
            "country:FI",
            "corp:NordicsMember",
            "D_GEO_NORDICS",
        ): "Finland is a constituent market of the Nordic region",
        (
            "country:IS",
            "corp:NordicsMember",
            "D_GEO_NORDICS",
        ): "Iceland is a constituent market of the Nordic region",
        (
            "country:NO",
            "corp:NordicsMember",
            "D_GEO_NORDICS",
        ): "Norway is a constituent market of the Nordic region",
        (
            "country:SE",
            "corp:NordicsMember",
            "D_GEO_NORDICS",
        ): "Sweden is a constituent market of the Nordic region",
        (
            "country:CA",
            "srt:NorthAmericaMember",
            "D_GEO_NORTH_AMER",
        ): "Canada is a sub-region of North America",
        (
            "country:US",
            "srt:NorthAmericaMember",
            "D_GEO_NORTH_AMER",
        ): "United States is a sub-region of North America",
        (
            "country:MX",
            "srt:NorthAmericaMember",
            "D_GEO_USMCA",
        ): "Mexico is part of North America under USMCA / NAFTA trade bloc",
        (
            "country:US",
            "srt:NorthAmericaMember",
            "D_GEO_USMCA",
        ): "United States is part of North America under USMCA",
        (
            "country:CA",
            "srt:NorthAmericaMember",
            "D_GEO_USMCA",
        ): "Canada is part of North America under USMCA",
        (
            "country:CN",
            "corp:GreaterChinaMember",
            "D_GEO_GREATER_CHINA",
        ): "Mainland China is a constituent of Greater China",
        (
            "country:HK",
            "corp:GreaterChinaMember",
            "D_GEO_GREATER_CHINA",
        ): "Hong Kong SAR is a constituent of Greater China",
        (
            "country:TW",
            "corp:GreaterChinaMember",
            "D_GEO_GREATER_CHINA",
        ): "Taiwan is a constituent of Greater China",
        (
            "country:MO",
            "corp:GreaterChinaMember",
            "D_GEO_GREATER_CHINA",
        ): "Macau SAR is a constituent of Greater China",
        (
            "corp:GreaterChinaMember",
            "srt:AsiaPacificMember",
            "D_GEO_APAC",
        ): "Greater China rolls up into Asia-Pacific",
        (
            "srt:EuropeMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "Europe is a constituent of EMEA",
        (
            "srt:MiddleEastMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "Middle East is a constituent of EMEA",
        (
            "srt:AfricaMember",
            "srt:EMEAMember",
            "D_GEO_EMEA",
        ): "Africa is a constituent of EMEA",
        (
            "srt:CentralAmericaMember",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "Central America rolls up into Latin America",
        (
            "srt:SouthAmericaMember",
            "srt:LatinAmericaMember",
            "D_GEO_CORP_LATAM",
        ): "South America rolls up into Latin America",
    }
)

EDGES: tuple[GeoEdge, ...] = tuple(
    GeoEdge(
        child=child,
        parent=parent,
        scheme=scheme,
        relation="MERONYMY_PART_OF",
        notes=_EDGE_NOTES.get((child, parent, scheme), ""),
    )
    for child, parent, scheme in _EDGE_ROWS
)

__all__ = [
    "EDGES",
    "GeoEdge",
]
