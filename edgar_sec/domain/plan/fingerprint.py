from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def plan_fingerprint_from_sorted_keys(
    plan_meta: dict[str, Any], sorted_keys: Iterable[str]
) -> str:
    digest = hashlib.sha256()
    digest.update(
        b'{"catalog_id":'
        + json.dumps(plan_meta.get("catalog_id"), separators=(",", ":")).encode()
        + b',"locator_keys":['
    )
    first = True
    for key in sorted_keys:
        if not first:
            digest.update(b",")
        digest.update(json.dumps(key, separators=(",", ":")).encode())
        first = False
    digest.update(
        b'],"plan_id":'
        + json.dumps(plan_meta.get("plan_id"), separators=(",", ":")).encode()
        + b',"scope":'
        + json.dumps(plan_meta.get("scope"), separators=(",", ":")).encode()
        + b"}"
    )
    return digest.hexdigest()[:32]
