from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

from .hashing import hash_dict


def load_template(template_path: str) -> str:
    return Path(template_path).read_text(encoding="utf-8")


def load_prompt_template(repo_root: str, template_id: str, template_version: str) -> str:
    """Load a prompt template from the prompts directory.
    
    Args:
        repo_root: Root directory of the repo
        template_id: Template identifier (e.g., "prompts/instagram_copy" or "instagram_copy")
        template_version: Template version (e.g., "v1.0.0")
    
    Returns:
        The template content as a string
    """
    # Try multiple possible locations
    possible_paths = [
        Path(repo_root) / template_id / template_version / "template.md",
        Path(repo_root) / "prompts" / template_id / template_version / "template.md",
        Path(repo_root) / "sigilzero" / template_id / template_version / "template.md",
        Path(repo_root) / "sigilzero" / "prompts" / template_id / template_version / "template.md",
    ]
    
    for template_path in possible_paths:
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
    
    raise FileNotFoundError(f"Template not found for {template_id}/{template_version}. Tried: {possible_paths}")


def render_template(template: str, params: Dict[str, Any]) -> str:
    """Very small, dependency-free renderer using Python format()."""
    # Ensure stable stringification for nested params
    safe_params = dict(params)
    for k, v in list(safe_params.items()):
        if isinstance(v, (dict, list)):
            safe_params[k] = json.dumps(v, ensure_ascii=False, indent=2)
    return template.format(**safe_params)


def params_hash(params: Dict[str, Any]) -> str:
    return hash_dict(params)
