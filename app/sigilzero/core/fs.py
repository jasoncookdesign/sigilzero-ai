from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def ensure_dir(path: Path | str) -> Path:
    """Ensure directory exists, creating as needed."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_text(path: Path | str, content: str) -> None:
    """Write text content to file, creating parent directories as needed."""
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(content, encoding="utf-8")


def write_json(path: Path | str, data: Any) -> None:
    """Write JSON data to file with canonical deterministic formatting.
    
    Phase 1.0 Determinism: JSON snapshots must be byte-stable for hashing.
    - sort_keys=True for deterministic key order
    - ensure_ascii=False to preserve Unicode
    - indent=2 for readability (stable whitespace)
    - trailing newline enforced
    """
    p = Path(path)
    ensure_dir(p.parent)
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)
    # Enforce trailing newline for POSIX compliance and git-friendliness
    if not json_str.endswith("\n"):
        json_str += "\n"
    p.write_text(json_str, encoding="utf-8")
