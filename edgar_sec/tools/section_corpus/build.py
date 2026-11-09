"""Bank section-detector corpus specimens from named filings.

A jobs JSON names specimens by form, accession, and document; each body
is normalized once and banked with the taxonomy it is judged against.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.processing_profiles import get_family_entry
from edgar_sec.domain.sec_urls import archives_url
from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.storage.atomic import atomic_write_json

# Slugs whose families opt into run-in section titles (see the corpus
# README); the corpus test applies the same convention.
RUN_IN_SLUGS = frozenset({"form_n23c3"})

_DEFAULT_CORPUS = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/engine/forms/sections/section_corpus"
)


def _taxonomy_payload(items: tuple[ItemDefinition, ...]) -> list[dict[str, Any]]:
    """Serialize taxonomy items in the corpus's banked shape."""
    return [
        {
            "item": it.item,
            "part": it.part,
            "names": list(it.names),
            "optional": it.optional,
            "early": it.early,
        }
        for it in items
    ]


def _taxonomy_items(payload: list[dict[str, Any]]) -> tuple[ItemDefinition, ...]:
    """Rebuild taxonomy items from the corpus's banked shape."""
    return tuple(
        ItemDefinition(
            item=it["item"],
            part=it["part"],
            names=tuple(it["names"]),
            optional=it["optional"],
            early=it["early"],
        )
        for it in payload
    )


def bank_specimen(
    corpus_dir: Path,
    job: dict[str, Any],
    raw_bytes: bytes,
    *,
    refresh_taxonomy: bool = False,
) -> dict[str, Any]:
    """Normalize one body and bank its text, taxonomy, and resolutions."""
    slug = job["slug"]
    form = job["form"]
    accession = job["accession"]
    document = job["document"]
    entry = get_family_entry(form)
    if entry is None or not entry.taxonomy_items:
        raise ValueError(f"no registered taxonomy for form {form!r}")

    taxonomies_path = corpus_dir / "taxonomies.json"
    taxonomies: dict[str, Any] = (
        json.loads(taxonomies_path.read_text(encoding="utf-8"))
        if taxonomies_path.exists()
        else {}
    )
    if slug not in taxonomies or refresh_taxonomy:
        taxonomies[slug] = _taxonomy_payload(entry.taxonomy_items)
        atomic_write_json(taxonomies_path, dict(sorted(taxonomies.items())))
    items = _taxonomy_items(taxonomies[slug])

    result = normalize_document(raw_bytes, form=form, document_path=document)
    text_rel = f"texts/{slug}/{accession}__{document}"
    text_path = corpus_dir / text_rel
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(result.text, encoding="utf-8")
    toc_span = (
        [result.toc_span.start_line, result.toc_span.end_line]
        if result.toc_span
        else None
    )
    seq = detect_section_sequence(
        result.text,
        family=slug,
        taxonomy_items=items,
        toc_span=tuple(toc_span) if toc_span else None,
        run_in_titles=slug in RUN_IN_SLUGS,
    )
    labels = [s.item_identifier for s in seq.sections]
    record = {
        "id": f"{slug}/{accession}__{document}",
        "family": slug,
        "form": form,
        "accession": accession,
        "document": document,
        "era": job.get("era"),
        "text": text_rel,
        "toc_span": toc_span,
        "baseline": labels,
        "expected": labels,
    }

    index_path = corpus_dir / "index.json"
    index: list[dict[str, Any]] = (
        json.loads(index_path.read_text(encoding="utf-8"))
        if index_path.exists()
        else []
    )
    index = [e for e in index if e["id"] != record["id"]]
    index.append(record)
    index.sort(key=lambda e: e["id"])
    atomic_write_json(index_path, index)
    return record


def _fetch_body(job: dict[str, Any], client: SecHttpClient) -> bytes:
    """Fetch one specimen body from the EDGAR archives."""
    cik = int(job["accession"].split("-")[0])
    url = archives_url(cik, job["accession"], job["document"])
    return client.get_bytes(url)


def main(argv: list[str] | None = None) -> int:
    """Bank every specimen named by a jobs JSON file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, help="Jobs JSON path.")
    parser.add_argument("--corpus-dir", default=str(_DEFAULT_CORPUS))
    parser.add_argument(
        "--specimen-dir",
        default=None,
        help="Local body directory; a job's 'file' names its body there.",
    )
    parser.add_argument("--refresh-taxonomy", action="store_true")
    args = parser.parse_args(argv)

    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    corpus_dir = Path(args.corpus_dir)
    client: SecHttpClient | None = None
    for job in jobs:
        if args.specimen_dir and job.get("file"):
            raw = (Path(args.specimen_dir) / job["file"]).read_bytes()
        else:
            if client is None:
                user_agent = get_env("SEC_USER_AGENT")
                if not user_agent:
                    raise ValueError(
                        "SEC_USER_AGENT must be set in the process environment"
                    )
                client = SecHttpClient(
                    user_agent=user_agent, rate_limiter=RateLimiter()
                )
            raw = _fetch_body(job, client)
        record = bank_specimen(
            corpus_dir, job, raw, refresh_taxonomy=args.refresh_taxonomy
        )
        print(f"{record['id']}: {len(record['baseline'])} sections")
    return 0


if __name__ == "__main__":
    sys.exit(main())
