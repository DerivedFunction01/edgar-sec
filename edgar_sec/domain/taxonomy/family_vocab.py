"""Lexical tables for universe-scale company-family assignment.

Every table is immutable: a caller mutating one would make the assignment depend on call
order rather than on the universe. ``SPV_MARKERS`` alone decides whether a name belongs
to the SPV namespace; ``SPONSOR_BOUNDARY_WORDS`` only locates the sponsor in a title.
"""

from __future__ import annotations

from types import MappingProxyType

from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES


FAMILY_INDEX_SCHEMA_VERSION = "2.0.0"

SPV_PREFIX = "spv:"
ENTITY_PREFIX = "entity:"
CIK_PREFIX = "cik:"

# Tokens stripped only from the tail of a name.
CORPORATE_DESIGNATORS: frozenset[str] = frozenset(
    {
        "ag",
        "bv",
        "co",
        "corp",
        "corporation",
        "gmbh",
        "inc",
        "incorporated",
        "kgaa",
        "lda",
        "limited",
        "llc",
        "llp",
        "lp",
        "ltd",
        "nv",
        "plc",
        "pty",
        "pvt",
        "sa",
        "se",
        "sl",
        "sociedad",
        "spa",
        "srl",
        "anonima",
    }
)

IDENTITY_NOUNS: frozenset[str] = frozenset(
    {"bancorp", "bankshares", "fund", "group", "holding", "trust"}
)

SPV_MARKERS: frozenset[str] = frozenset(
    {
        "asset",
        "backed",
        "bond",
        "cert",
        "certificate",
        "class",
        "collateralised",
        "collateralized",
        "debenture",
        "grantor",
        "mezzanine",
        "mortgage",
        "note",
        "owner",
        "pass",
        "receivable",
        "receivables",
        "secured",
        "securitisation",
        "securitization",
        "securities",
        "security",
        "senior",
        "series",
        "spv",
        "subordinated",
        "through",
        "tranche",
        "trust",
    }
)

SPONSOR_BOUNDARY_WORDS: frozenset[str] = frozenset(
    SPV_MARKERS
    | {
        "abs",
        "auto",
        "bank",
        "banking",
        "beneficiary",
        "capital",
        "commercial",
        "company",
        "corporation",
        "credit",
        "finance",
        "financial",
        "fund",
        "group",
        "guaranteed",
        "holding",
        "industrial",
        "insurance",
        "investments",
        "lease",
        "leasing",
        "obligation",
        "partners",
        "solutions",
        "special",
        "structured",
        "systems",
        "ventures",
    }
)

# Known institution spellings, keyed by their space-squashed form.
INSTITUTION_ALIASES: MappingProxyType[str, str] = MappingProxyType(
    {
        "alphafund": "alphafund",
        "axisfund": "axisfund",
        "bankofamerica": "bankofamerica",
        "breakawaygrowth": "breakawaygrowth",
        "cgf2021": "cgf2021",
        "coinvest": "coinvest",
        "equitymultiple": "equitymultiple",
        "healthcareventures": "healthcareventures",
        "hgcapital": "hgcapital",
        "jpmorgan": "jpmorgan",
        "jpmorganchase": "jpmorganchase",
        "jpmorganchasebank": "jpmorganchase",
        "jvgp": "jvgp",
        "morganstanleygroup": "morganstanley",
        "noreastercapital": "noreastercapital",
        "realtymogul": "realtymogul",
        "risefund": "risefund",
        "smarttrust": "smarttrust",
        "venturefund": "venturefund",
    }
)

AMBIGUOUS_POSTAL_CODES: frozenset[str] = frozenset(
    {
        "al",
        "ar",
        "ca",
        "co",
        "de",
        "hi",
        "ia",
        "id",
        "in",
        "ks",
        "ma",
        "me",
        "ms",
        "mt",
        "ne",
        "oh",
        "ok",
        "or",
        "pa",
        "sc",
    }
)

ORDINAL_WORDS: MappingProxyType[str, str] = MappingProxyType(
    {
        "first": "1st",
        "second": "2nd",
        "third": "3rd",
        "fourth": "4th",
        "fifth": "5th",
        "sixth": "6th",
        "seventh": "7th",
        "eighth": "8th",
        "ninth": "9th",
        "tenth": "10th",
    }
)

ABBR_MAP: MappingProxyType[str, str] = MappingProxyType(
    {
        "mort": "mortgage",
        "mrt": "mortgage",
        "mor": "mortgage",
        "mtg": "mortgage",
        "pas": "pass",
        "thr": "through",
        "thro": "through",
        "th": "through",
        "thru": "through",
        "cert": "certificate",
        "certs": "certificate",
        "crt": "certificate",
        "crts": "certificate",
        "cer": "certificate",
        "ce": "certificate",
        "ser": "series",
        "sec": "securities",
        "asst": "asset",
        "ast": "asset",
        "ass": "asset",
        "bck": "backed",
        "bkd": "backed",
        "nts": "notes",
        "ln": "loan",
        "eq": "equity",
        "hm": "home",
        "fd": "fund",
    }
)

# token -> (expansion, allowed previous, allowed next). An empty set means no constraint
# on that side; both neighbours are checked because "tr" is "trust" after a security
# type and "series" elsewhere.
CONTEXT_RULES: MappingProxyType[str, tuple[str, frozenset[str], frozenset[str]]] = (
    MappingProxyType(
        {
            "com": ("commercial", frozenset(), frozenset({"mortgage", "mor", "mrt"})),
            "comm": ("commercial", frozenset(), frozenset({"mortgage", "mor", "mrt"})),
            "ps": (
                "pass",
                frozenset({"mortgage", "mor", "mrt"}),
                frozenset({"through", "thr", "th", "thro"}),
            ),
            "bk": (
                "backed",
                frozenset({"asset", "asst", "as", "ast", "ln"}),
                frozenset({"certificate", "crt", "cer"}),
            ),
            "as": (
                "asset",
                frozenset({"ln", "loan"}),
                frozenset({"bk", "bck", "bkd", "backed"}),
            ),
            "tr": (
                "trust",
                frozenset(
                    {
                        "securities",
                        "sec",
                        "ln",
                        "eq",
                        "bck",
                        "bk",
                        "mortgage",
                        "d",
                        "series",
                    }
                ),
                frozenset(),
            ),
            "ct": (
                "certificate",
                frozenset({"through", "thr", "th", "pass", "pas", "ps"}),
                frozenset(),
            ),
            "sr": (
                "series",
                frozenset({"certificate", "crt", "cert", "ce"}),
                frozenset(),
            ),
            "se": (
                "series",
                frozenset({"certificate", "ce", "cert", "crt"}),
                frozenset(),
            ),
            "srs": (
                "series",
                frozenset({"certificate", "certs", "crt", "through", "thr"}),
                frozenset(),
            ),
        }
    )
)

# Singular forms, applied after abbreviation expansion. Curated rather than an `-s`
# rule: EDGAR carries individual names in `SURNAME FIRSTNAME` form, so folding `owens`
# to `owen` or `woods` to `wood` would merge different people.
PLURAL_MAP: MappingProxyType[str, str] = MappingProxyType(
    {
        "acquisitions": "acquisition",
        "advisors": "advisor",
        "assets": "asset",
        "bonds": "bond",
        "certificates": "certificate",
        "classes": "class",
        "companies": "company",
        "credits": "credit",
        "debentures": "debenture",
        "enterprises": "enterprise",
        "equities": "equity",
        "fundings": "funding",
        "funds": "fund",
        "holdings": "holding",
        "industries": "industry",
        "investments": "investment",
        "investors": "investor",
        "loans": "loan",
        "mortgages": "mortgage",
        "networks": "network",
        "notes": "note",
        "opportunities": "opportunity",
        "partners": "partner",
        "policies": "policy",
        "portfolios": "portfolio",
        "products": "product",
        "properties": "property",
        "receivables": "receivable",
        "resources": "resource",
        "securities": "security",
        "situations": "situation",
        "technologies": "technology",
    }
)

UMBRELLA_PHRASE = "a series of"

MIN_SQUASH_CHARS = 6


def strippable_postal_codes() -> frozenset[str]:
    """State codes carrying no identity, i.e. all of them but the ambiguous words."""
    return (
        frozenset(code.lower() for code in STATE_POSTAL_CODES) - AMBIGUOUS_POSTAL_CODES
    )


def rule_fingerprint_payload() -> dict[str, object]:
    """Every input that can move a family key, for the cache manifest fingerprint."""
    return {
        "schema_version": FAMILY_INDEX_SCHEMA_VERSION,
        "spv_markers": sorted(SPV_MARKERS),
        "boundary_words": sorted(SPONSOR_BOUNDARY_WORDS),
        "aliases": dict(sorted(INSTITUTION_ALIASES.items())),
        "abbreviations": dict(sorted(ABBR_MAP.items())),
        "plurals": dict(sorted(PLURAL_MAP.items())),
        "ordinals": dict(sorted(ORDINAL_WORDS.items())),
        "designators": sorted(CORPORATE_DESIGNATORS),
        "identity_nouns": sorted(IDENTITY_NOUNS),
        "postal_codes": sorted(strippable_postal_codes()),
    }


__all__ = [
    "ABBR_MAP",
    "AMBIGUOUS_POSTAL_CODES",
    "CONTEXT_RULES",
    "CORPORATE_DESIGNATORS",
    "FAMILY_INDEX_SCHEMA_VERSION",
    "IDENTITY_NOUNS",
    "INSTITUTION_ALIASES",
    "MIN_SQUASH_CHARS",
    "ORDINAL_WORDS",
    "PLURAL_MAP",
    "SPONSOR_BOUNDARY_WORDS",
    "SPV_MARKERS",
    "SPV_PREFIX",
    "ENTITY_PREFIX",
    "CIK_PREFIX",
    "UMBRELLA_PHRASE",
    "rule_fingerprint_payload",
    "strippable_postal_codes",
]
