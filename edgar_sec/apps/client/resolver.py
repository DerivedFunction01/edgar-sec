"""Entity metadata resolution and cohort warming for client applications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.submissions.models import Address, EntityProfile, Listing
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.filing_catalog.paths import (
    SNAPSHOT_FILE,
    resolve_filing_catalog_paths,
)


def resolve_entity_profile(
    identifier: str | int | Cik,
    artifacts_root: Path | None = None,
) -> EntityProfile:
    """Resolve an entity profile by CIK or ticker, warming cohorts if needed."""
    catalog_paths = resolve_filing_catalog_paths(artifacts_root)
    profile_pattern = str(catalog_paths.snapshots_root / "**" / SNAPSHOT_FILE)

    norm_str = str(identifier).strip()
    is_cik_numeric = isinstance(identifier, (int, Cik)) or (
        isinstance(identifier, str) and norm_str.isdigit()
    )

    if not is_cik_numeric:
        cik_val = _resolve_ticker_to_cik(
            norm_str.upper(), profile_pattern, artifacts_root
        )
        if cik_val is not None:
            norm_str = str(cik_val)
            is_cik_numeric = True

    if is_cik_numeric:
        cik_int = int(norm_str)
        return _query_profile_by_cik(cik_int, profile_pattern)

    return EntityProfile(cik=Cik.from_raw(1), name=norm_str)


def _resolve_ticker_to_cik(
    ticker: str,
    profile_pattern: str,
    artifacts_root: Path | None,
) -> int | None:
    """Lookup CIK from ticker in catalog company profiles or cohort registry."""
    with connect() as con:
        try:
            row = con.execute(
                "SELECT cik FROM read_parquet(?) "
                "WHERE list_contains(list_transform(listings, x -> upper(x.ticker)), ?) "
                "LIMIT 1",
                [profile_pattern, ticker],
            ).fetchone()
            if row:
                return int(row[0])
        except Exception:
            pass

    try:
        from edgar_sec.engine.xbrl.domain import load_domain_taxonomy

        tax = load_domain_taxonomy()
        ind = tax.find_industry(ticker)
        if ind is not None:
            return int(ind.cik)
    except Exception:
        pass

    return _warm_and_resolve_cohort_ticker(ticker, artifacts_root)


def _warm_and_resolve_cohort_ticker(
    ticker: str,
    artifacts_root: Path | None,
) -> int | None:
    """Resolve ticker against official tickers cohort, warming if missing."""
    from edgar_sec.foundation.runtime.paths import resolve_paths
    from edgar_sec.infra.storage.cohort.catalog import (
        CohortCatalog,
        CohortIdentifierError,
    )
    from edgar_sec.infra.storage.cohort.paths import CohortPaths
    from edgar_sec.pipelines.cohort.sources import refresh_official_source

    root = (
        artifacts_root if artifacts_root is not None else resolve_paths().artifacts_root
    )
    paths = CohortPaths(root)
    if artifacts_root is None and not paths.catalog_file.is_file():
        return None
    catalog = CohortCatalog(paths)
    try:
        record = catalog.resolve_cohort_identifier("tickers")
    except CohortIdentifierError:
        try:
            record = refresh_official_source(
                "company_tickers", paths=paths, catalog=catalog
            )
        except Exception:
            return None

    dataset_path = paths.cohort_dataset_file(record.cohort_id)
    if not dataset_path.is_file():
        return None

    with connect() as con:
        row = con.execute(
            "SELECT cik_value FROM read_parquet(?) WHERE upper(raw_name) = ? LIMIT 1",
            [str(dataset_path), ticker],
        ).fetchone()
        return int(row[0]) if row else None


def _query_profile_by_cik(cik_int: int, profile_pattern: str) -> EntityProfile:
    """Query company profile row from parquet snapshot."""
    query = (
        "SELECT cik, identity, classification, addresses, listings, incorporation, reporting "
        "FROM read_parquet(?) "
        "WHERE try_cast(cik AS BIGINT) = ? "
        "LIMIT 1"
    )
    with connect() as con:
        try:
            row = con.execute(query, [profile_pattern, cik_int]).fetchone()
        except Exception:
            row = None

    if not row:
        return EntityProfile(cik=Cik(cik_int), name=f"CIK {cik_int:010d}")

    _, identity, classification, addresses, listings, incorporation, reporting = row
    name = (identity or {}).get("name") or f"CIK {cik_int:010d}"
    sic_code = (classification or {}).get("sic_code")
    sic_desc = (classification or {}).get("sic_description")
    state_inc = (incorporation or {}).get("state")
    fiscal_end = (reporting or {}).get("fiscal_year_end")

    parsed_listings = tuple(
        Listing(ticker=item["ticker"], exchange=item.get("exchange") or "")
        for item in (listings or ())
        if isinstance(item, dict) and "ticker" in item
    )

    mailing = None
    if addresses and addresses.get("mailing"):
        m = addresses["mailing"]
        mailing = Address(
            street1=m.get("street1"),
            city=m.get("city"),
            state_or_country=m.get("state_or_country"),
            zip_code=m.get("zip_code"),
        )

    business = None
    if addresses and addresses.get("business"):
        b = addresses["business"]
        business = Address(
            street1=b.get("street1"),
            city=b.get("city"),
            state_or_country=b.get("state_or_country"),
            zip_code=b.get("zip_code"),
        )

    return EntityProfile(
        cik=Cik(cik_int),
        name=name,
        sic_code=sic_code,
        sic_description=sic_desc,
        state_of_incorporation=state_inc,
        fiscal_year_end=fiscal_end,
        listings=parsed_listings,
        mailing_address=mailing,
        business_address=business,
    )


__all__ = ["resolve_entity_profile"]
