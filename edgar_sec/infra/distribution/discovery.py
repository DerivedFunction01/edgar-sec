"""Filesystem discovery and status inspection for worker bundles."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .guards import (
    BUNDLE_MANIFEST_NAME,
    assert_receipt_affinity,
    read_bundle_manifest,
)
from .protocol import WorkerReceipt
from .receipt import RECEIPT_FILE, read_receipt, verify_receipt_digests


@dataclass(frozen=True, slots=True)
class DiscoveredBundle:
    bundle_dir: Path
    pipeline: str
    work_id: str
    worker_id: str
    chunk_count: int
    chunk_ids: tuple[int, ...]
    state: str
    receipt: WorkerReceipt | None = None
    detail: str = ""


def discover_bundles(
    root: Path,
    pipeline: str | None = None,
    work_id: str | None = None,
) -> list[DiscoveredBundle]:
    if not root.is_dir():
        return []

    discovered: list[DiscoveredBundle] = []
    for manifest_path in root.glob(f"**/{BUNDLE_MANIFEST_NAME}"):
        bundle_dir = manifest_path.parent
        try:
            manifest = read_bundle_manifest(bundle_dir)
        except (ValueError, OSError):
            continue

        pipe = str(manifest.get("pipeline", ""))
        item_id = str(manifest.get("work_id", ""))
        if pipeline and pipe != pipeline:
            continue
        if work_id and item_id != work_id:
            continue

        worker_id = str(manifest.get("worker_id", bundle_dir.name))
        chunk_ids = tuple(manifest.get("chunk_ids", ()))
        receipt_file = bundle_dir / RECEIPT_FILE
        receipt: WorkerReceipt | None = None
        state = "pending"
        detail = ""

        if receipt_file.is_file():
            try:
                receipt = read_receipt(receipt_file)
                assert_receipt_affinity(receipt, manifest)
                valid, err = verify_receipt_digests(receipt, bundle_dir)
                if valid:
                    state = "completed"
                else:
                    state = "corrupt"
                    detail = err
            except (ValueError, OSError) as exc:
                state = "corrupt"
                detail = str(exc)

        discovered.append(
            DiscoveredBundle(
                bundle_dir=bundle_dir,
                pipeline=pipe,
                work_id=item_id,
                worker_id=worker_id,
                chunk_count=len(chunk_ids),
                chunk_ids=chunk_ids,
                state=state,
                receipt=receipt,
                detail=detail,
            )
        )

    return sorted(
        discovered,
        key=lambda bundle: (bundle.pipeline, bundle.work_id, bundle.worker_id),
    )


def resolve_bundle_choice(
    bundles: Sequence[DiscoveredBundle],
    select: Callable[[list[str]], str],
) -> DiscoveredBundle | None:
    if not bundles:
        return None
    if len(bundles) == 1:
        return bundles[0]

    lines = [
        f"  {index}. {bundle.worker_id:<12} ({bundle.state}) - "
        f"{len(bundle.chunk_ids)} chunks [{bundle.bundle_dir}]"
        for index, bundle in enumerate(bundles, start=1)
    ]
    try:
        index = int(select(lines))
        if 1 <= index <= len(bundles):
            return bundles[index - 1]
    except (TypeError, ValueError):
        pass
    return None
