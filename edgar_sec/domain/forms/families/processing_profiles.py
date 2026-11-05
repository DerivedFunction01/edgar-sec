"""Processing profile catalog for form families.

Aggregates family declarations from annual/, quarterly/, and current/.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.common.schemas import CoverCheckboxSchema
from edgar_sec.domain.forms.families.annual.processing import (
    PROFILE as ANNUAL_PROFILE,
    PROFILE_20F as ANNUAL_PROFILE_20F,
)
from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.current.checkmarks import (
    EIGHT_K_CHECKBOX_SCHEMA,
    SIX_K_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.current.processing import (
    PROFILE as CURRENT_PROFILE,
)
from edgar_sec.domain.forms.families.form_12b25.checkmarks import (
    FORM_12B25_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_12b25.processing import (
    PROFILE_FORM_12B25,
)
from edgar_sec.domain.forms.families.form_12b25.taxonomy import FORM_12B25_ITEMS
from edgar_sec.domain.forms.families.form_15.checkmarks import (
    FORM_15_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_13f.processing import PROFILE_FORM_13F
from edgar_sec.domain.forms.families.form_11k.checkmarks import (
    FORM_11K_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_11k.processing import PROFILE_FORM_11K
from edgar_sec.domain.forms.families.form_11k.taxonomy import FORM_11K_ITEMS
from edgar_sec.domain.forms.families.form_14a.checkmarks import (
    FORM_14A_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_14a.processing import PROFILE_FORM_14A
from edgar_sec.domain.forms.families.form_14a.taxonomy import FORM_14A_ITEMS
from edgar_sec.domain.forms.families.form_15.processing import PROFILE_FORM_15
from edgar_sec.domain.forms.families.form_424b.processing import PROFILE_FORM_424B
from edgar_sec.domain.forms.families.form_424b.taxonomy import FORM_424B_ITEMS
from edgar_sec.domain.forms.families.form_f1.checkmarks import (
    FORM_F1_CHECKBOX_SCHEMA,
    FORM_F2_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f1.processing import (
    PROFILE_FORM_F1,
    PROFILE_FORM_F2,
)
from edgar_sec.domain.forms.families.form_f1.taxonomy import (
    FORM_F1_ITEMS,
    FORM_F2_ITEMS,
)
from edgar_sec.domain.forms.families.form_f3.checkmarks import (
    FORM_F3_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f3.processing import PROFILE_FORM_F3
from edgar_sec.domain.forms.families.form_f3.taxonomy import FORM_F3_ITEMS
from edgar_sec.domain.forms.families.form_f4.checkmarks import (
    FORM_F4_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f4.processing import PROFILE_FORM_F4
from edgar_sec.domain.forms.families.form_f4.taxonomy import FORM_F4_ITEMS
from edgar_sec.domain.forms.families.form_40f.checkmarks import (
    FORM_40F_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_40f.processing import PROFILE_FORM_40F
from edgar_sec.domain.forms.families.form_f6.checkmarks import (
    FORM_F6_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_f6.processing import PROFILE_FORM_F6
from edgar_sec.domain.forms.families.form_f6.taxonomy import FORM_F6_ITEMS
from edgar_sec.domain.forms.families.form_fn.checkmarks import (
    FORM_FN_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_fn.processing import PROFILE_FORM_FN
from edgar_sec.domain.forms.families.form_mjds.checkmarks import (
    FORM_F7_CHECKBOX_SCHEMA,
    FORM_F8_CHECKBOX_SCHEMA,
    FORM_F9_CHECKBOX_SCHEMA,
    FORM_F10_CHECKBOX_SCHEMA,
    FORM_F80_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_mjds.processing import (
    PROFILE_FORM_F7,
    PROFILE_FORM_F8,
    PROFILE_FORM_F9,
    PROFILE_FORM_F10,
    PROFILE_FORM_F80,
)
from edgar_sec.domain.forms.families.form_mjds.taxonomy import (
    FORM_F7_ITEMS,
    FORM_F8_ITEMS,
    FORM_F9_ITEMS,
    FORM_F10_ITEMS,
    FORM_F80_ITEMS,
)
from edgar_sec.domain.forms.families.form_suppl.processing import PROFILE_FORM_SUPPL
from edgar_sec.domain.forms.families.form_425.processing import PROFILE_FORM_425
from edgar_sec.domain.forms.families.form_fwp.processing import PROFILE_FORM_FWP
from edgar_sec.domain.forms.families.form_fwp.taxonomy import FORM_FWP_ITEMS
from edgar_sec.domain.forms.families.form_d.processing import PROFILE_FORM_D
from edgar_sec.domain.forms.families.form_ncen.processing import PROFILE_N_CEN
from edgar_sec.domain.forms.families.form_nmfp.processing import PROFILE_N_MFP
from edgar_sec.domain.forms.families.form_nport.processing import PROFILE_NPORT
from edgar_sec.domain.forms.families.form_npx.processing import PROFILE_N_PX
from edgar_sec.domain.forms.families.form_497.processing import PROFILE_FORM_497
from edgar_sec.domain.forms.families.form_497.taxonomy import FORM_497_ITEMS
from edgar_sec.domain.forms.families.form_ncsr.processing import PROFILE_FORM_NCSR
from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS
from edgar_sec.domain.forms.families.form_nq.processing import PROFILE_FORM_NQ
from edgar_sec.domain.forms.families.form_nq.taxonomy import FORM_NQ_ITEMS
from edgar_sec.domain.forms.families.form_nsar.processing import PROFILE_FORM_NSAR
from edgar_sec.domain.forms.families.form_nsar.taxonomy import FORM_NSAR_ITEMS
from edgar_sec.domain.forms.families.form144.processing import PROFILE_FORM_144
from edgar_sec.domain.forms.families.ownership.processing import (
    PROFILE_FORM_3,
    PROFILE_FORM_4,
    PROFILE_FORM_5,
)
from edgar_sec.domain.forms.families.quarterly.checkmarks import (
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.quarterly.processing import (
    PROFILE as QUARTERLY_PROFILE,
)
from edgar_sec.domain.forms.families.registration.checkmarks import (
    S1_CHECKBOX_SCHEMA,
    S3_CHECKBOX_SCHEMA,
    S4_CHECKBOX_SCHEMA,
    S8_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.registration.processing import (
    PROFILE_S1,
    PROFILE_S3,
    PROFILE_S4,
    PROFILE_S8,
)


from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.annual.taxonomy import (
    FORM_10K_ITEMS,
    FORM_20F_ITEMS,
)
from edgar_sec.domain.forms.families.current.taxonomy import FORM_8K_ITEMS
from edgar_sec.domain.forms.families.quarterly.taxonomy import FORM_10Q_ITEMS
from edgar_sec.domain.forms.families.registration.taxonomy import (
    FORM_S1_ITEMS,
    FORM_S3_ITEMS,
    FORM_S4_ITEMS,
    FORM_S8_ITEMS,
)
from edgar_sec.domain.forms.families.beneficial_ownership.processing import (
    PROFILE_SCHEDULE_13D,
    PROFILE_SCHEDULE_13G,
)
from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13D_ITEMS,
    SCHEDULE_13G_ITEMS,
)
from edgar_sec.domain.forms.families.form_tender.checkmarks import (
    TENDER_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_25nse.processing import PROFILE_FORM_25NSE
from edgar_sec.domain.forms.families.form_12reg.checkmarks import (
    FORM_25_CHECKBOX_SCHEMA,
    FORM_8A_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_12reg.processing import (
    PROFILE_FORM_25,
    PROFILE_FORM_8A,
    PROFILE_FORM_8B,
)
from edgar_sec.domain.forms.families.form_12reg.taxonomy import FORM_8A_ITEMS
from edgar_sec.domain.forms.families.form_abs_ee.processing import PROFILE_ABS_EE
from edgar_sec.domain.forms.families.form_abs_reports.checkmarks import (
    ABS_REPORTS_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.form_abs_reports.processing import (
    PROFILE_ABS_REPORTS,
)
from edgar_sec.domain.forms.families.form_abs_reports.taxonomy import (
    ABS_REPORTS_ITEMS,
)
from edgar_sec.domain.forms.families.form_c.processing import PROFILE_FORM_C

from edgar_sec.domain.forms.families.form_sd.checkmarks import SD_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.form_sd.processing import PROFILE_SD
from edgar_sec.domain.forms.families.form_sd.taxonomy import FORM_SD_ITEMS

from edgar_sec.domain.forms.families.form_rega.processing import (
    PROFILE_REGA_ANNUAL,
    PROFILE_REGA_CURRENT,
    PROFILE_REGA_EXIT,
    PROFILE_REGA_OFFERING,
    PROFILE_REGA_SEMI_ANNUAL,
)
from edgar_sec.domain.forms.families.form_rega.taxonomy import (
    FORM_1SA_ITEMS,
    FORM_1U_ITEMS,
)

from edgar_sec.domain.forms.families.form_drs.processing import PROFILE_DRS
from edgar_sec.domain.forms.families.form_tender.processing import PROFILE_TENDER
from edgar_sec.domain.forms.families.form_tender.taxonomy import SCHEDULE_TO_ITEMS


# ARS rides the generic segmentation profile (T4.10 disposition):
# no family package, no taxonomy, no analyzer of its own.
PROFILE_ARS = DocumentProcessingProfile(
    family="ARS",
    version="v1",
    allowed_operations=frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    ),
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
)


# Raw-ride profiles (2026-11-05 disposition): the primary is a native
# XML submission, so no text path exists and no family package is built.
PROFILE_NCR = DocumentProcessingProfile(
    family="N-CR",
    version="v1",
    allowed_operations=frozenset({AcquisitionOperation.RAW}),
    preferred_operation=AcquisitionOperation.RAW,
)

PROFILE_ATSN = DocumentProcessingProfile(
    family="ATS-N",
    version="v1",
    allowed_operations=frozenset({AcquisitionOperation.RAW}),
    preferred_operation=AcquisitionOperation.RAW,
)

PROFILE_MAI = DocumentProcessingProfile(
    family="MA-I",
    version="v1",
    allowed_operations=frozenset({AcquisitionOperation.RAW}),
    preferred_operation=AcquisitionOperation.RAW,
)


@dataclass(frozen=True, slots=True)
class ProcessingCatalogEntry:
    """Entry in the processing catalog."""

    family: str
    profile: DocumentProcessingProfile
    cover_checkbox_schema: CoverCheckboxSchema | None = None
    taxonomy_items: tuple[ItemDefinition, ...] = ()


FAMILY_PROCESSING_PROFILES: tuple[ProcessingCatalogEntry, ...] = (
    ProcessingCatalogEntry(
        family="10-K",
        profile=ANNUAL_PROFILE,
        cover_checkbox_schema=ANNUAL_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_10K_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="20-F",
        profile=ANNUAL_PROFILE_20F,
        cover_checkbox_schema=ANNUAL_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_20F_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="10-Q",
        profile=QUARTERLY_PROFILE,
        cover_checkbox_schema=QUARTERLY_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_10Q_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="8-K",
        profile=CURRENT_PROFILE,
        cover_checkbox_schema=EIGHT_K_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_8K_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="6-K",
        profile=CURRENT_PROFILE,
        cover_checkbox_schema=SIX_K_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="S-1",
        profile=PROFILE_S1,
        cover_checkbox_schema=S1_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S1_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="S-3",
        profile=PROFILE_S3,
        cover_checkbox_schema=S3_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S3_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="S-4",
        profile=PROFILE_S4,
        cover_checkbox_schema=S4_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S4_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="S-8",
        profile=PROFILE_S8,
        cover_checkbox_schema=S8_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S8_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-1",
        profile=PROFILE_FORM_F1,
        cover_checkbox_schema=FORM_F1_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F1_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-2",
        profile=PROFILE_FORM_F2,
        cover_checkbox_schema=FORM_F2_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F2_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-3",
        profile=PROFILE_FORM_F3,
        cover_checkbox_schema=FORM_F3_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F3_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-4",
        profile=PROFILE_FORM_F4,
        cover_checkbox_schema=FORM_F4_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F4_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-7",
        profile=PROFILE_FORM_F7,
        cover_checkbox_schema=FORM_F7_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F7_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-8",
        profile=PROFILE_FORM_F8,
        cover_checkbox_schema=FORM_F8_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F8_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-9",
        profile=PROFILE_FORM_F9,
        cover_checkbox_schema=FORM_F9_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F9_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-10",
        profile=PROFILE_FORM_F10,
        cover_checkbox_schema=FORM_F10_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F10_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-80",
        profile=PROFILE_FORM_F80,
        cover_checkbox_schema=FORM_F80_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F80_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="40-F",
        profile=PROFILE_FORM_40F,
        cover_checkbox_schema=FORM_40F_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="SUPPL",
        profile=PROFILE_FORM_SUPPL,
    ),
    ProcessingCatalogEntry(
        family="F-6",
        profile=PROFILE_FORM_F6,
        cover_checkbox_schema=FORM_F6_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_F6_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="F-N",
        profile=PROFILE_FORM_FN,
        cover_checkbox_schema=FORM_FN_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="424B",
        profile=PROFILE_FORM_424B,
        taxonomy_items=FORM_424B_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="FWP",
        profile=PROFILE_FORM_FWP,
        taxonomy_items=FORM_FWP_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="425",
        profile=PROFILE_FORM_425,
    ),
    ProcessingCatalogEntry(
        family="3",
        profile=PROFILE_FORM_3,
    ),
    ProcessingCatalogEntry(
        family="4",
        profile=PROFILE_FORM_4,
    ),
    ProcessingCatalogEntry(
        family="5",
        profile=PROFILE_FORM_5,
    ),
    ProcessingCatalogEntry(
        family="144",
        profile=PROFILE_FORM_144,
    ),
    ProcessingCatalogEntry(
        family="D",
        profile=PROFILE_FORM_D,
    ),
    ProcessingCatalogEntry(
        family="15",
        profile=PROFILE_FORM_15,
        cover_checkbox_schema=FORM_15_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="12B-25",
        profile=PROFILE_FORM_12B25,
        cover_checkbox_schema=FORM_12B25_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_12B25_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="13F",
        profile=PROFILE_FORM_13F,
    ),
    ProcessingCatalogEntry(
        family="N-PORT",
        profile=PROFILE_NPORT,
    ),
    ProcessingCatalogEntry(
        family="N-CEN",
        profile=PROFILE_N_CEN,
    ),
    ProcessingCatalogEntry(
        family="N-PX",
        profile=PROFILE_N_PX,
    ),
    ProcessingCatalogEntry(
        family="N-MFP",
        profile=PROFILE_N_MFP,
    ),
    ProcessingCatalogEntry(
        family="N-CSR",
        profile=PROFILE_FORM_NCSR,
        taxonomy_items=FORM_NCSR_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="N-Q",
        profile=PROFILE_FORM_NQ,
        taxonomy_items=FORM_NQ_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="NSAR",
        profile=PROFILE_FORM_NSAR,
        taxonomy_items=FORM_NSAR_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="497",
        profile=PROFILE_FORM_497,
        taxonomy_items=FORM_497_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="14A",
        profile=PROFILE_FORM_14A,
        cover_checkbox_schema=FORM_14A_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_14A_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="11-K",
        profile=PROFILE_FORM_11K,
        cover_checkbox_schema=FORM_11K_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_11K_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="13D",
        profile=PROFILE_SCHEDULE_13D,
        taxonomy_items=SCHEDULE_13D_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="13G",
        profile=PROFILE_SCHEDULE_13G,
        taxonomy_items=SCHEDULE_13G_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="SC TO",
        profile=PROFILE_TENDER,
        cover_checkbox_schema=TENDER_CHECKBOX_SCHEMA,
        taxonomy_items=SCHEDULE_TO_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="DRS",
        profile=PROFILE_DRS,
    ),
    ProcessingCatalogEntry(
        family="25-NSE",
        profile=PROFILE_FORM_25NSE,
    ),
    ProcessingCatalogEntry(
        family="C",
        profile=PROFILE_FORM_C,
    ),
    ProcessingCatalogEntry(
        family="ABS-EE",
        profile=PROFILE_ABS_EE,
    ),
    ProcessingCatalogEntry(
        family="ABS",
        profile=PROFILE_ABS_REPORTS,
        cover_checkbox_schema=ABS_REPORTS_CHECKBOX_SCHEMA,
        taxonomy_items=ABS_REPORTS_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="25",
        profile=PROFILE_FORM_25,
        cover_checkbox_schema=FORM_25_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="8-A",
        profile=PROFILE_FORM_8A,
        cover_checkbox_schema=FORM_8A_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_8A_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="8-B",
        profile=PROFILE_FORM_8B,
        taxonomy_items=FORM_8A_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="SD",
        profile=PROFILE_SD,
        cover_checkbox_schema=SD_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_SD_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="1-A",
        profile=PROFILE_REGA_OFFERING,
    ),
    ProcessingCatalogEntry(
        family="1-K",
        profile=PROFILE_REGA_ANNUAL,
    ),
    ProcessingCatalogEntry(
        family="1-Z",
        profile=PROFILE_REGA_EXIT,
    ),
    ProcessingCatalogEntry(
        family="1-SA",
        profile=PROFILE_REGA_SEMI_ANNUAL,
        taxonomy_items=FORM_1SA_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="1-U",
        profile=PROFILE_REGA_CURRENT,
        taxonomy_items=FORM_1U_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="ARS",
        profile=PROFILE_ARS,
    ),
    ProcessingCatalogEntry(
        family="N-CR",
        profile=PROFILE_NCR,
    ),
    ProcessingCatalogEntry(
        family="ATS-N",
        profile=PROFILE_ATSN,
    ),
    ProcessingCatalogEntry(
        family="MA-I",
        profile=PROFILE_MAI,
    ),
)

_FAMILY_ENTRY_BY_FAMILY = {entry.family: entry for entry in FAMILY_PROCESSING_PROFILES}


def get_family_entry(family: str | None) -> ProcessingCatalogEntry | None:
    """Get catalog data for a canonical or aliased filing form."""
    if not family:
        return None
    normalized = resolve_alias(family) or family.strip().upper()
    return _FAMILY_ENTRY_BY_FAMILY.get(normalized)


def get_family_profile(family: str) -> DocumentProcessingProfile | None:
    """Get the processing profile for a given family.

    Returns None if the family has no registered profile.
    """
    entry = get_family_entry(family)
    return entry.profile if entry is not None else None


LAZY_INDEX_FORM_FAMILIES: frozenset[str] = frozenset(
    {
        "10-K",
        "10-Q",
        "8-K",
        "20-F",
        "S-1",
        "S-3",
        "S-4",
        "S-8",
        "3",
        "4",
        "5",
        "144",
        "D",
        "13D",
        "13G",
    }
)


def get_lazy_index_trigger(family: str | None) -> tuple[str, str] | None:
    """Return trigger ID and version for declared lazy-index families."""
    entry = get_family_entry(family)
    if entry is None or entry.family not in LAZY_INDEX_FORM_FAMILIES:
        return None
    return f"{entry.family}.exact_form", "1"


__all__ = [
    "FAMILY_PROCESSING_PROFILES",
    "LAZY_INDEX_FORM_FAMILIES",
    "PROFILE_ARS",
    "PROFILE_ATSN",
    "PROFILE_MAI",
    "PROFILE_NCR",
    "ANNUAL_PROFILE",
    "QUARTERLY_PROFILE",
    "CURRENT_PROFILE",
    "ProcessingCatalogEntry",
    "get_family_entry",
    "get_family_profile",
    "get_lazy_index_trigger",
]
