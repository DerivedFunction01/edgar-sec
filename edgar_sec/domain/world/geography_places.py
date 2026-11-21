"""Geography places: country and region records for the DAG nodes.

Names and match phrases are the union programme's standings for
the hierarchy's countries; weights and gazetteers stay behind.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Country:
    """One country's declared name and match phrases."""

    code: str
    name: str
    phrases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Region:
    """One region member node's declared name and match phrases."""

    node: str
    name: str
    phrases: tuple[str, ...] = ()


_COUNTRY_RECORDS: tuple[Country, ...] = (
    Country(code="AE", name="United Arab Emirates", phrases=("uae", "emirates")),
    Country(code="AR", name="Argentina", phrases=("argentina", "argentine")),
    Country(
        code="AT",
        name="Austria",
        phrases=("austria", "austrian", "österreich", "oesterreich"),
    ),
    Country(code="AU", name="Australia", phrases=("australia", "australian")),
    Country(
        code="BE",
        name="Belgium",
        phrases=("belgium", "belgian", "belgique", "belgië", "belgie"),
    ),
    Country(code="BG", name="Bulgaria", phrases=("bulgaria", "bulgarian")),
    Country(code="BR", name="Brazil", phrases=("brazil", "reais", "brl", "brasil")),
    Country(code="CA", name="Canada", phrases=("canada", "canadian")),
    Country(
        code="CH",
        name="Switzerland",
        phrases=("switzerland", "swiss", "chf", "schweiz", "suisse", "svizzera"),
    ),
    Country(code="CL", name="Chile", phrases=("chile", "chilean")),
    Country(
        code="CN",
        name="China",
        phrases=("china", "chinese", "prc", "p.r.c.", "people's republic of china"),
    ),
    Country(code="CO", name="Colombia", phrases=("colombia", "colombian")),
    Country(
        code="CZ",
        name="Czech Republic",
        phrases=(
            "czech republic",
            "czechia",
            "czech",
            "česká republika",
            "ceska republika",
            "česko",
            "cesko",
        ),
    ),
    Country(code="DE", name="Germany", phrases=("germany", "german", "deutschland")),
    Country(code="DK", name="Denmark", phrases=("denmark", "danish", "danmark")),
    Country(code="EG", name="Egypt", phrases=("egypt", "egyptian")),
    Country(code="ES", name="Spain", phrases=("spain", "spanish", "españa")),
    Country(code="FI", name="Finland", phrases=("finland", "finnish", "suomi")),
    Country(code="FR", name="France", phrases=("france", "french")),
    Country(code="GB", name="United Kingdom", phrases=("united kingdom",)),
    Country(code="HK", name="Hong Kong", phrases=("hong kong", "hk")),
    Country(
        code="HU",
        name="Hungary",
        phrases=("hungary", "hungarian", "magyarország", "magyarorszag"),
    ),
    Country(code="ID", name="Indonesia", phrases=("indonesia", "indonesian")),
    Country(code="IL", name="Israel", phrases=("israel", "israeli")),
    Country(code="IN", name="India", phrases=("india", "indian", "lakh", "crore")),
    Country(code="IS", name="Iceland", phrases=("iceland", "icelandic", "ísland")),
    Country(code="IT", name="Italy", phrases=("italy", "italian", "italia")),
    Country(code="JP", name="Japan", phrases=("japan", "japanese", "nihon", "nippon")),
    Country(code="KR", name="South Korea", phrases=("south korea",)),
    Country(
        code="LU",
        name="Luxembourg",
        phrases=("luxembourg", "luxembourgish", "lëtzebuerg", "letzebuerg"),
    ),
    Country(code="MA", name="Morocco", phrases=("morocco", "moroccan", "maroc")),
    Country(code="MO", name="Macau", phrases=("macau", "macanese")),
    Country(code="MX", name="Mexico", phrases=("mexico", "mexican", "méxico")),
    Country(code="MY", name="Malaysia", phrases=("malaysia", "malaysian")),
    Country(code="NG", name="Nigeria", phrases=("nigeria", "nigerian")),
    Country(
        code="NL",
        name="Netherlands",
        phrases=("netherlands", "dutch", "holland", "nederland"),
    ),
    Country(code="NO", name="Norway", phrases=("norway", "norwegian", "norge")),
    Country(code="NZ", name="New Zealand", phrases=("new zealand", "nz", "aotearoa")),
    Country(code="PE", name="Peru", phrases=("peru", "peruvian", "perú")),
    Country(
        code="PH",
        name="Philippines",
        phrases=("philippines", "philippine", "filipino", "pilipinas"),
    ),
    Country(code="PL", name="Poland", phrases=("poland", "polish", "polska")),
    Country(code="QA", name="Qatar", phrases=("qatar", "qatari")),
    Country(code="RO", name="Romania", phrases=("romania", "romanian", "românia")),
    Country(code="SA", name="Saudi Arabia", phrases=("saudi arabia", "saudi")),
    Country(code="SE", name="Sweden", phrases=("sweden", "swedish", "sverige")),
    Country(code="SG", name="Singapore", phrases=("singapore", "singaporean")),
    Country(code="SK", name="Slovakia", phrases=("slovakia", "slovak", "slovensko")),
    Country(code="TH", name="Thailand", phrases=("thailand", "thai")),
    Country(code="TW", name="Taiwan", phrases=("taiwan", "taiwanese")),
    Country(code="US", name="United States", phrases=("united states",)),
    Country(code="VN", name="Vietnam", phrases=("vietnam", "vietnamese", "việt nam")),
    Country(code="ZA", name="South Africa", phrases=("south africa", "south african")),
)

_REGION_RECORDS: tuple[Region, ...] = (
    Region(node="corp:ANZMember", name="ANZ", phrases=("anz",)),
    Region(node="corp:ASEANMember", name="ASEAN", phrases=("asean",)),
    Region(node="corp:BeneluxMember", name="Benelux", phrases=("benelux",)),
    Region(
        node="corp:CEEMember", name="CEE", phrases=("cee", "central and eastern europe")
    ),
    Region(node="corp:DACHMember", name="DACH", phrases=("dach",)),
    Region(
        node="corp:GreaterChinaMember", name="Greater China", phrases=("greater china",)
    ),
    Region(node="corp:MENAMember", name="MENA", phrases=("mena",)),
    Region(node="corp:NordicsMember", name="Nordics", phrases=("nordics", "nordic")),
    Region(node="srt:AfricaMember", name="Africa", phrases=("africa",)),
    Region(node="srt:AmericasMember", name="Americas", phrases=("americas",)),
    Region(
        node="srt:AsiaPacificMember",
        name="Asia Pacific",
        phrases=("asia pacific", "apac"),
    ),
    Region(node="srt:CaribbeanMember", name="Caribbean", phrases=("caribbean",)),
    Region(
        node="srt:CentralAmericaMember",
        name="Central America",
        phrases=("central america",),
    ),
    Region(node="srt:EMEAMember", name="EMEA", phrases=("emea",)),
    Region(node="srt:EuropeMember", name="Europe", phrases=("europe",)),
    Region(
        node="srt:EuropeanUnionMember",
        name="European Union",
        phrases=("european union",),
    ),
    Region(
        node="srt:LatinAmericaMember", name="Latin America", phrases=("latin america",)
    ),
    Region(node="srt:MiddleEastMember", name="Middle East", phrases=("middle east",)),
    Region(
        node="srt:NorthAmericaMember", name="North America", phrases=("north america",)
    ),
    Region(
        node="srt:SouthAmericaMember", name="South America", phrases=("south america",)
    ),
)

COUNTRIES: MappingProxyType[str, Country] = MappingProxyType(
    {record.code: record for record in _COUNTRY_RECORDS}
)
REGIONS: MappingProxyType[str, Region] = MappingProxyType(
    {record.node: record for record in _REGION_RECORDS}
)

__all__ = [
    "COUNTRIES",
    "REGIONS",
    "Country",
    "Region",
]
