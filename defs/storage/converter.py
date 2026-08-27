"""Batch dataset conversion between interchangeable file backends."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .dataset import Dataset
from .models import BatchReceipt
from .predicates import QueryPlan
from .protocols import Record


class DatasetConverter:
    """Copy logical records from one initialized dataset to another.

    Transformations are deliberately plain Python callables. The source
    backend can optimize its own read path, while the target controls its
    physical batch write. Neither side requires pandas.
    """

    def __init__(
        self, source: Dataset, target: Dataset, *, batch_size: int = 1000
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.source = source
        self.target = target
        self.batch_size = batch_size

    def copy(
        self,
        query: QueryPlan | None = None,
        *,
        transform: Callable[[Record], Record] | None = None,
    ) -> dict[str, Any]:
        batch: list[Record] = []
        records = 0
        bytes_written = 0
        receipts: list[BatchReceipt] = []

        def flush() -> None:
            nonlocal records, bytes_written
            if not batch:
                return
            items = list(batch)
            batch.clear()
            receipt = self.target.write_batch(items)
            receipts.append(receipt)
            records += receipt.record_count
            bytes_written += receipt.byte_count

        for record in self.source.load(query):
            batch.append(transform(dict(record)) if transform else dict(record))
            if len(batch) >= self.batch_size:
                flush()
        flush()
        self.target.commit()
        return {
            "records": records,
            "bytes_written": bytes_written,
            "batches": len(receipts),
            "durable": all(receipt.durable for receipt in receipts),
        }
