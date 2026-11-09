"""Canonical SEC form-family alias registry and suffix collapse.

Single source of truth for mapping a raw form string to its canonical family; suffix
stripping runs before alias lookup.
"""

from __future__ import annotations

# Canonical aliases grouped by form family. Amendment and submission suffixes
# are included explicitly so callers can map raw form strings directly.
FORM_FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "10-K": (
        "10-K",
        "10-K/A",
        "10-K405",
        "10-K405/A",
        "10-KSB",
        "10-KSB/A",
        "10KSB",
        "10KSB/A",
        "10KSB40",
        "10KSB40/A",
        "10-KT",
        "10-KT/A",
        "10KT405",
        "10KT405/A",
    ),
    "10-Q": (
        "10-Q",
        "10-Q/A",
        "10-QSB",
        "10-QSB/A",
        "10QSB",
        "10QSB/A",
        "10-QT",
        "10-QT/A",
    ),
    "8-K": (
        "8-K",
        "8-K/A",
        "8-K12B",
        "8-K12B/A",
        "8-K12G3",
        "8-K12G3/A",
        "8-K15D5",
        "8-K15D5/A",
    ),
    "20-F": (
        "20-F",
        "20-F/A",
        "20FR12B",
        "20FR12B/A",
        "20FR12G",
        "20FR12G/A",
        "20FR12G3",
    ),
    "6-K": (
        "6-K",
        "6-K/A",
    ),
    "3": (
        "3",
        "3/A",
    ),
    "4": (
        "4",
        "4/A",
    ),
    "5": (
        "5",
        "5/A",
    ),
    "144": (
        "144",
        "144/A",
    ),
    "MA-I": (
        "MA-I",
        "MA-I/A",
    ),
    "D": (
        "D",
        "D/A",
        "REGDEX",
        "REGDEX/A",
    ),
    "13F": (
        "13F",
        "13F/A",
        "13F-HR",
        "13F-HR/A",
        "13F-NT",
        "13F-NT/A",
        "13F-CTR",
        "13F-CTR/A",
        "13F-E",
        "13F-E/A",
        "13FCONP",
        "13FCONP/A",
    ),
    "13D": (
        "13D",
        "13D/A",
        "SC 13D",
        "SC 13D/A",
        "SCHEDULE 13D",
        "SCHEDULE 13D/A",
    ),
    "13G": (
        "13G",
        "13G/A",
        "SC 13G",
        "SC 13G/A",
        "SCHEDULE 13G",
        "SCHEDULE 13G/A",
    ),
    "S-1": (
        "S-1",
        "S-1/A",
        "S-1MEF",
        "S-1MEF/A",
        "S-1POS",
        "S-1/A-POS",
    ),
    "S-3": (
        "S-3",
        "S-3/A",
        "S-3ASR",
        "S-3D",
        "S-3D/A",
        "S-3DPOS",
        "S-3MEF",
    ),
    "S-4": (
        "S-4",
        "S-4 POS",
        "S-4/A",
        "S-4EF",
        "S-4EF/A",
        "S-4MEF",
    ),
    "S-8": (
        "S-8",
        "S-8 POS",
        "S-8/A",
    ),
    "14A": (
        "14A",
        "14A/A",
        "DEF 14A",
        "DEF 14C",
        "DEFA14A",
        "DEFA14C",
        "DEFC14A",
        "DEFC14C",
        "DEFM14A",
        "DEFM14C",
        "DEFN14A",
        "DEFR14A",
        "DEFR14C",
        "DEFS14A",
        "DEFS14C",
        "PRE 14A",
        "PRE 14C",
        "PREA14A",
        "PREA14C",
        "PREC14A",
        "PREC14C",
        "PREM14A",
        "PREM14C",
        "PREN14A",
        "PRER14A",
        "PRER14C",
        "PRES14A",
        "PRES14C",
        "PRRN14A",
        "DFAN14A",
        "DFRN14A",
        "PX14A6G",
        "PX14A6N",
    ),
    "12B-25": (
        "12B-25",
        "12B-25/A",
        "NT 10-K",
        "NT 10-K/A",
        "NT 10-Q",
        "NT 10-Q/A",
        "NT 20-F",
        "NT 20-F/A",
        "NT 11-K",
        "NT 11-K/A",
        "NT 10-D",
        "NT 10-D/A",
        "NT 15D2",
        "NT 15D2/A",
        "SP 15D2",
        "SP 15D2/A",
        "NT N-CEN",
        "NT NPORT-EX",
        "NT NPORT-P",
        "NT-NCEN",
        "NT-NCSR",
        "NT-NCSR/A",
        "NT-NSAR",
        "NT-NSAR/A",
        "NTFNCEN",
        "NTFNCSR",
        "NTFNSAR",
        "NTN 10K",
        "NTN 10Q",
        "NTN 11K",
        "NTN 20F",
        "NTN 10D",
        "NTN15D2",
    ),
    "15": (
        "15",
        "15/A",
        "15-12B",
        "15-12B/A",
        "15-12G",
        "15-12G/A",
        "15-15D",
        "15-15D/A",
        "15F-12B",
        "15F-12G",
        "15F-12G/A",
        "15F-15D",
        "15F-15D/A",
    ),
    "11-K": (
        "11-K",
        "11-K/A",
        "11-KT",
        "11-KT/A",
    ),
    "424B": (
        "424B",
        "424B1",
        "424B2",
        "424B3",
        "424B4",
        "424B5",
        "424B7",
        "424B8",
        "424A",
        "424H",
        "424H/A",
    ),
    "FWP": ("FWP",),
    "425": ("425",),
    "N-PORT": (
        "N-PORT",
        "NPORT-P",
        "NPORT-P/A",
        "NPORT-EX",
        "NPORT-EX/A",
    ),
    "N-CEN": (
        "N-CEN",
        "N-CEN/A",
    ),
    "N-PX": (
        "N-PX",
        "N-PX/A",
        "N-PX CTR",
    ),
    "N-MFP": (
        "N-MFP",
        "N-MFP/A",
        "N-MFP2",
        "N-MFP2/A",
        "N-MFP3",
        "N-MFP3/A",
    ),
    "N-CR": (
        "N-CR",
        "N-CR/A",
    ),
    "N-CSR": (
        "N-CSR",
        "N-CSR/A",
        "N-CSRS",
        "N-CSRS/A",
    ),
    "N-Q": (
        "N-Q",
        "N-Q/A",
    ),
    "NSAR": (
        "NSAR",
        "NSAR-A",
        "NSAR-A/A",
        "NSAR-AT",
        "NSAR-B",
        "NSAR-B/A",
        "NSAR-BT",
        "NSAR-BT/A",
        "NSAR-U",
        "NSAR-U/A",
    ),
    "497": (
        "497",
        "497AD",
        "497H2",
        "497J",
        "497K",
        "497K3A",
        "497VPU",
        "497VPI",
        "497VPSUB",
    ),
    "485": (
        "485APOS",
        "485A24F",
        "485BPOS",
        "485B24F",
        "485BXT",
        "485BXTF",
        "486APOS",
        "486A24E",
        "486BPOS",
        "486B24E",
        "486BXT",
    ),
    "N-14": (
        "N-14",
        "N-14/A",
        "N-14 8C",
        "N-14 8C/A",
        "N-14MEF",
    ),
    "N-2": (
        "N-2",
        "N-2/A",
        "N-2ASR",
        "N-2MEF",
        "N-2 POSASR",
    ),
    "N-VP": (
        "N-VP",
        "N-VP/A",
        "N-VPFS",
        "N-VPFS/A",
    ),
    "N-4": (
        "N-4",
        "N-4/A",
    ),
    "N-6": (
        "N-6",
        "N-6/A",
    ),
    "F-1": (
        "F-1",
        "F-1/A",
        "F-1MEF",
    ),
    "F-2": (
        "F-2",
        "F-2/A",
    ),
    "F-3": (
        "F-3",
        "F-3/A",
        "F-3ASR",
        "F-3D",
        "F-3DPOS",
        "F-3MEF",
    ),
    "F-4": (
        "F-4",
        "F-4/A",
        "F-4EF",
        "F-4MEF",
        "F-4 POS",
    ),
    "F-6": (
        "F-6",
        "F-6/A",
        "F-6EF",
        "F-6 POS",
    ),
    "F-7": ("F-7",),
    "F-8": (
        "F-8",
        "F-8/A",
        "F-8 POS",
    ),
    "F-9": (
        "F-9",
        "F-9/A",
        "F-9 POS",
        "F-9EF",
    ),
    "F-10": (
        "F-10",
        "F-10/A",
        "F-10EF",
        "F-10POS",
    ),
    "F-80": (
        "F-80",
        "F-80/A",
        "F-80POS",
    ),
    "F-N": (
        "F-N",
        "F-N/A",
    ),
    "40-F": (
        "40-F",
        "40-F/A",
    ),
    "SUPPL": ("SUPPL",),
    "SC TO": (
        "SC TO",
        "SC TO-T",
        "SC TO-T/A",
        "SC TO-I",
        "SC TO-I/A",
        "SC TO-C",
        "SC 14D9",
        "SC 14D9/A",
        "SC14D9C",
        "SC14D9F",
        "SC14D9F/A",
        "SC 14D1",
        "SC 14D1/A",
        "SC14D1F",
        "SC14D1F/A",
        "SC 13E1",
        "SC 13E1/A",
        "SC 13E3",
        "SC 13E3/A",
        "SC 13E4",
        "SC 13E4/A",
    ),
    "DRS": (
        "DRS",
        "DRS/A",
        "DRSLTR",
    ),
    "25": (
        "25",
        "25/A",
    ),
    "25-NSE": (
        "25-NSE",
        "25-NSE/A",
    ),
    "8-A": (
        "8-A",
        "8-A12B",
        "8-A12B/A",
        "8-A12G",
        "8-A12G/A",
        "8A12BEF",
        "8A12BT",
        "8A12BT/A",
    ),
    "8-B": (
        "8-B",
        "8-B12B",
        "8-B12B/A",
        "8-B12G",
    ),
    "1-A": (
        "1-A",
        "1-A/A",
        "1-A POS",
        "1-A-W",
        "1-A-W/A",
        "253G1",
        "253G2",
        "253G3",
        "253G4",
    ),
    "1-K": (
        "1-K",
        "1-K/A",
    ),
    "1-Z": (
        "1-Z",
        "1-Z/A",
    ),
    "1-SA": (
        "1-SA",
        "1-SA/A",
    ),
    "1-U": (
        "1-U",
        "1-U/A",
    ),
    "SD": (
        "SD",
        "SD/A",
    ),
    "ARS": (
        "ARS",
        "ARS/A",
    ),
    "ABS-EE": (
        "ABS-EE",
        "ABS-EE/A",
    ),
    "ABS": (
        "ABS-15G",
        "ABS-15G/A",
        "10-D",
        "10-D/A",
    ),
    "ATS-N": (
        "ATS-N",
        "ATS-N/CA",
        "ATS-N/MA",
        "ATS-N/OFA",
        "ATS-N/UA",
        "ATS-N-W",
    ),
    "18-K": (
        "18-K",
        "18-K/A",
    ),
    "S-6": (
        "S-6",
        "S-6/A",
        "487",
    ),
    "40-17G": (
        "40-17G",
        "40-17G/A",
        "40-17GCS",
    ),
    "40-17F1": (
        "40-17F1",
        "40-17F1/A",
    ),
    "40-17F2": (
        "40-17F2",
        "40-17F2/A",
    ),
    "40-APP": (
        "40-APP",
        "40-APP/A",
    ),
    "40-24B2": (
        "40-24B2",
        "40-24B2/A",
    ),
    "N-30D": (
        "N-30D",
        "N-30D/A",
        "N-30B-2",
        "N-30B-2/A",
    ),
    "C": (
        "C",
        "C/A",
        "C-U",
        "C-AR",
        "C-AR/A",
        "C-TR",
        "C-W",
        "C-AR-W",
        "C-TR-W",
    ),
    "NRSRO-CE": ("NRSRO-CE",),
    "N-54C": ("N-54C",),
    "SF-1": ("SF-1",),
    "U-12-IB": ("U-12-IB",),
    "ANNLRPT": ("ANNLRPT",),
    "S-B": ("S-B",),
    "SB-1": ("SB-1",),
    "35-APP": ("35-APP",),
    "U-12-IA": ("U-12-IA",),
    "U-33-S": ("U-33-S",),
    "UNDER": ("UNDER",),
    "2-E": ("2-E",),
}

# Suffixes stripped when collapsing a raw form string to its base family.
# Order matters: each entry is removed at most once, so "10-K/A-POS" needs
# "-POS" removed before "/A".
FORM_FAMILY_SUFFIXES: tuple[str, ...] = (
    "_A",
    "_W",
    "_POS",
    "-POS",
    " POS",
    "MEF",
    "-W",
    "/A",
)


def _build_alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for family, aliases in FORM_FAMILY_ALIASES.items():
        for alias in aliases:
            lookup[alias.upper()] = family
    return lookup


_ALIAS_LOOKUP: dict[str, str] = _build_alias_lookup()


def form_family(form: str) -> str:
    """Collapse amendment and submission suffixes into the base form family.

    A form that is *entirely* suffixes (``/A``) returns the original, not an empty string.
    """
    form_str = str(form)
    base = form_str.upper().strip()
    for suffix in FORM_FAMILY_SUFFIXES:
        base = base.removesuffix(suffix)
    return base.strip("_-") or form_str


def resolve_alias(form: str | None) -> str | None:
    """Resolve a raw form string to its canonical family, or None if unknown."""
    if not form:
        return None
    form_str = str(form).strip().upper()
    direct = _ALIAS_LOOKUP.get(form_str)
    if direct is not None:
        return direct
    family = form_family(form_str)
    direct = _ALIAS_LOOKUP.get(family)
    if direct is not None:
        return direct
    return family if family in FORM_FAMILY_ALIASES else None


def aliases_for_family(family: str) -> tuple[str, ...]:
    """Return the canonical alias tuple for a form family."""
    return FORM_FAMILY_ALIASES.get(str(family).upper(), ())


def is_transition_form(form: str | None) -> bool:
    """True for a periodic family's transition (T) variant, per the registry.

    The squashed stem must extend the squashed family with a T: 10-KT and
    10-QT/A qualify; unrelated T-suffixed forms (13F-NT, SC TO-T) do not.
    """
    if not form:
        return False
    family = resolve_alias(form)
    if family is None:
        return False
    squash = lambda text: "".join(c for c in text if c.isalnum())  # noqa: E731
    stem, base = squash(str(form).removesuffix("/A")), squash(family)
    return stem.startswith(base) and len(stem) > len(base) and stem[len(base)] == "T"


__all__ = [
    "FORM_FAMILY_ALIASES",
    "FORM_FAMILY_SUFFIXES",
    "aliases_for_family",
    "form_family",
    "is_transition_form",
    "resolve_alias",
]
