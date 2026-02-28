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
    """Write JSON data to file, creating parent directories as needed."""
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
