from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Tuple


def canonical_json(obj: Any) -> str:
    """Canonical JSON for stable hashing: sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return "sha256:" + h.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(obj: Any) -> str:
    """Hash a JSON-serializable object (dict, Pydantic model, etc.)."""
    json_str = canonical_json(obj)
    return sha256_text(json_str)


def hash_pydantic_model(model: Any, *, exclude: Iterable[str] = ()) -> str:
    """Hash a Pydantic model (v1 or v2) by dumping to dict then canonicalizing."""
    try:
        d = model.model_dump(exclude=set(exclude))  # pydantic v2
    except Exception:
        d = model.dict(exclude=set(exclude))  # pydantic v1
    return sha256_text(canonical_json(d))


def hash_dict(d: Dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))
