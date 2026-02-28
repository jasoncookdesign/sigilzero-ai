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


def compute_inputs_hash(snapshot_hashes: Dict[str, str]) -> str:
    """Compute deterministic inputs_hash from snapshot hashes.
    
    Phase 1.0 Determinism: inputs_hash is computed from canonical snapshot hashes only.
    Order is alphabetical by key for determinism.
    
    Args:
        snapshot_hashes: Dict mapping snapshot name to its sha256 hash
                        e.g., {"brief": "sha256:abc...", "context": "sha256:def..."}
    
    Returns:
        Combined hash in format "sha256:..."
    """
    # Sort keys alphabetically for determinism
    sorted_items = sorted(snapshot_hashes.items())
    combined = canonical_json(dict(sorted_items))
    return sha256_text(combined)


def derive_run_id(inputs_hash: str, suffix: str = "") -> str:
    """Derive deterministic run_id from inputs_hash.
    
    Phase 1.0 Determinism: run_id is purely a function of inputs.
    
    Args:
        inputs_hash: The inputs_hash (sha256:...)
        suffix: Optional deterministic suffix (e.g., for retry logic)
    
    Returns:
        Deterministic run_id string
    """
    # Extract hex portion from "sha256:..." format
    if inputs_hash.startswith("sha256:"):
        hex_hash = inputs_hash[7:]
    else:
        hex_hash = inputs_hash
    
    # Use first 32 chars of hex as base run_id (128 bits = UUID-equivalent entropy)
    run_id = hex_hash[:32]
    
    if suffix:
        # Append deterministic suffix with separator
        run_id = f"{run_id}-{suffix}"
    
    return run_id
