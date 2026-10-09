"""Filesystem discovery and status inspection for distributed worker bundles."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .guards import BUNDLE_MANIFEST_NAME, read_bundle_manifest
from .protocol import WorkerReceipt
from .receipt import RECEIPT_FILE, read_receipt, verify_receipt_digests


@dataclass(frozen=True, slots=True)
class DiscoveredBundle:
    """Discovered worker bundle metadata and validation state."""

    bundle_dir: Path
    pipeline: str
    plan_id: str
    worker_id: str
    chunk_count: int
    chunk_ids: tuple[int, ...]
    state: str  # "pending", "completed", "corrupt"
    receipt: WorkerReceipt | None = None
    detail: str = ""


def discover_bundles(
    root: Path,
    pipeline: str | None = None,
    plan_id: str | None = None,
) -> list[DiscoveredBundle]:
    """Scan root hierarchy for valid exported worker bundles."""
    if not root.is_dir():
        return []

    discovered: list[DiscoveredBundle] = []
    # Walk directory structure looking for directories containing bundle.json
    for manifest_path in root.glob(f"**/{BUNDLE_MANIFEST_NAME}"):
        bundle_dir = manifest_path.parent
        try:
            manifest = read_bundle_manifest(bundle_dir)
        except (ValueError, OSError):
            continue

        pipe = str(manifest.get("pipeline", ""))
        p_id = str(manifest.get("plan_id", ""))
        if pipeline and pipe != pipeline:
            continue
        if plan_id and p_id != plan_id:
            continue

        worker_id = str(manifest.get("worker_id", bundle_dir.name))
        chunk_ids = tuple(manifest.get("chunk_ids", ()))
        chunk_count = int(manifest.get("chunk_count", len(chunk_ids)))

        receipt_file = bundle_dir / RECEIPT_FILE
        receipt: WorkerReceipt | None = None
        state = "pending"
        detail = ""

        if receipt_file.is_file():
            try:
                receipt = read_receipt(receipt_file)
                valid, err = verify_receipt_digests(receipt, bundle_dir)
                if valid:
                    state = "completed"
                else:
                    state = "corrupt"
                    detail = err
            except Exception as exc:  # noqa: BLE001
                state = "corrupt"
                detail = str(exc)

        discovered.append(
            DiscoveredBundle(
                bundle_dir=bundle_dir,
                pipeline=pipe,
                plan_id=p_id,
                worker_id=worker_id,
                chunk_count=chunk_count,
                chunk_ids=chunk_ids,
                state=state,
                receipt=receipt,
                detail=detail,
            )
        )

    return sorted(discovered, key=lambda b: (b.pipeline, b.plan_id, b.worker_id))


def resolve_bundle_choice(
    bundles: Sequence[DiscoveredBundle],
    select: Callable[[list[str]], str],
) -> DiscoveredBundle | None:
    """Interactively select a discovered bundle."""
    if not bundles:
        return None
    if len(bundles) == 1:
        return bundles[0]

    lines = [
        f"  {idx}. {b.worker_id:<12} ({b.state}) - {len(b.chunk_ids)} chunks [{b.bundle_dir}]"
        for idx, b in enumerate(bundles, start=1)
    ]
    try:
        ans = select(lines)
        idx = int(ans)
        if 1 <= idx <= len(bundles):
            return bundles[idx - 1]
    except (TypeError, ValueError):
        pass
    return None
