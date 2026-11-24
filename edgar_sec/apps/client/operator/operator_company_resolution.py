"""Name resolution, closed at the operation layer.

Scored candidates over the catalog's name data: an exact or clear
winner resolving, a near-tie refusing with the candidates listed.
"""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.operator.operator_company_names import (
    _EXACT_SCORE,
    _entry_dict,
    _normalize,
    score_name_candidates,
)
from edgar_sec.apps.client.operator.operator_tools import error_result


_SCORE_THRESHOLD = 0.6
_SCORE_MARGIN = 0.15


def _catalog_entries(session: Any, query: str) -> list[dict[str, Any]]:
    """Name entries from the landed catalog's company-profiles snapshot.

    The same profiles parquet the facade resolver reads; a SQL prefilter
    on the query's longest token bounds what reaches Python scoring.
    """
    facade = session.facade
    for attribute in (
        "company_candidates",
        "name_candidates",
        "company_name_candidates",
    ):
        provider = getattr(facade, attribute, None)
        if callable(provider):
            try:
                return [_entry_dict(item) for item in provider(query)]
            except TypeError:
                return [_entry_dict(item) for item in provider()]
    artifacts = getattr(facade, "artifacts_root", None)
    if not artifacts:
        try:
            from edgar_sec.foundation.runtime.paths import resolve_paths

            artifacts = resolve_paths().artifacts_root
        except Exception:  # noqa: BLE001 - no readable root reads as no candidates
            return []
    try:
        from edgar_sec.infra.storage.duckdb import connect
        from edgar_sec.pipelines.filing_catalog.paths import (
            SNAPSHOT_FILE,
            resolve_filing_catalog_paths,
        )

        paths = resolve_filing_catalog_paths(artifacts)
        if not list(paths.snapshots_root.glob(f"**/{SNAPSHOT_FILE}")):
            return []
        pattern = str(paths.snapshots_root / "**" / SNAPSHOT_FILE)
        tokens = [word for word in _normalize(query)[0].split() if len(word) >= 3]
        token = max(tokens, key=len) if tokens else query.strip()
        sql = (
            "SELECT cik, identity, listings FROM read_parquet(?) "
            "WHERE upper(identity.name) LIKE '%' || upper(?) || '%' LIMIT 500"
        )
        with connect() as con:
            rows = con.execute(sql, [pattern, token]).fetchall()
    except Exception:  # noqa: BLE001 - no readable catalog reads as no candidates
        return []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cik, identity, listings in rows:
        identity = identity or {}
        key = str(cik) or str(identity.get("name") or "")
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "name": str(identity.get("name") or ""),
                "cik": str(cik),
                "tickers": [
                    str(item["ticker"])
                    for item in (listings or ())
                    if isinstance(item, dict) and "ticker" in item
                ],
            }
        )
    return entries


def _cik_text(company: Any) -> str:
    cik = getattr(company, "cik", None)
    if cik is None:
        profile = getattr(company, "profile", None)
        cik = getattr(profile, "cik", None)
    to_10digit = getattr(cik, "to_10digit", None)
    if callable(to_10digit):
        return str(to_10digit())
    value = getattr(cik, "value", cik)
    return str(value) if value is not None else ""


def _is_placeholder(company: Any, identifier: str) -> bool:
    """The resolver's unresolved-name placeholder: CIK 1 named as the query."""
    profile = getattr(company, "profile", None)
    cik = getattr(profile, "cik", None)
    value = getattr(cik, "value", cik)
    return value in (1, "1") and str(getattr(profile, "name", "")) == identifier


def _company_summary(company: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(company, "name", "") or ""),
        "cik": _cik_text(company),
        "tickers": [str(t) for t in (getattr(company, "tickers", ()) or ())],
    }


def _resolve_company(session: Any, identifier: str, kind: str):
    """Resolve to (company, resolution, error); exactly one of company/error."""
    title = "Company"
    ident = identifier.strip()
    if not ident:
        return (
            None,
            {},
            error_result(kind, "refused", title, "company refused: no identifier"),
        )
    facade = session.facade
    if ident.isdigit():
        return facade.company(ident), {"via": "cik", "identifier": ident}, None
    try:
        direct = facade.company(ident)
    except Exception:  # noqa: BLE001 - an unresolvable ticker falls to names
        direct = None
    if direct is not None and not _is_placeholder(direct, ident):
        return direct, {"via": "ticker", "identifier": ident}, None
    candidates = score_name_candidates(ident, _catalog_entries(session, ident))
    resolution = {"via": "name", "identifier": ident, "candidates": candidates}
    if not candidates or candidates[0]["score"] < _SCORE_THRESHOLD:
        return (
            None,
            resolution,
            error_result(
                kind,
                "not_found",
                title,
                f"no company name matches: {ident}",
                {"candidates": candidates},
            ),
        )
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    exact_clear = top["score"] >= _EXACT_SCORE and (
        second is None or second["score"] < top["score"]
    )
    margin_clear = second is None or top["score"] - second["score"] >= _SCORE_MARGIN
    if not (exact_clear or margin_clear):
        return (
            None,
            resolution,
            error_result(
                kind,
                "refused",
                title,
                f"name is ambiguous: {ident}; refusing to pick between candidates",
                {"candidates": candidates},
            ),
        )
    return facade.company(top["cik"]), resolution, None
