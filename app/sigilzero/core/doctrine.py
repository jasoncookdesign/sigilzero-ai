from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from .hashing import sha256_bytes
from .schemas import DoctrineReference


ALLOWED_DOCTRINE_IDS = {
    "prompts/instagram_copy",
}


class DoctrineLoader:
    """Loads and validates versioned doctrine files.
    
    Phase 1.0 Determinism:
    - Doctrine files are versioned in-repo
    - Doctrine content is hashed
    - Doctrine hash participates in inputs_hash
    - Doctrine version + hash recorded in manifest
    """
    
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)
    
    def load_doctrine(
        self,
        doctrine_id: str,
        version: str,
        filename: str = "template.md"
    ) -> Tuple[str, DoctrineReference]:
        """Load a versioned doctrine file and compute its reference.
        
        Args:
            doctrine_id: Doctrine identifier (e.g., "prompts/instagram_copy")
            version: Version string (e.g., "v1.0.0")
            filename: Filename within version directory (default: "template.md")
        
        Returns:
            Tuple of (content, doctrine_reference)
        
        Raises:
            FileNotFoundError: If doctrine file not found
        """
        if doctrine_id not in ALLOWED_DOCTRINE_IDS:
            raise ValueError(f"Unsupported doctrine_id: {doctrine_id}")

        if doctrine_id.startswith("/") or ".." in doctrine_id.split("/"):
            raise ValueError(f"Unsafe doctrine_id: {doctrine_id}")

        if version.startswith("/") or ".." in version.split("/"):
            raise ValueError(f"Unsafe doctrine version: {version}")

        if filename.startswith("/") or ".." in filename.split("/"):
            raise ValueError(f"Unsafe doctrine filename: {filename}")

        # Try multiple possible locations
        possible_paths = [
            self.repo_root / doctrine_id / version / filename,
            self.repo_root / "sigilzero" / doctrine_id / version / filename,
            self.repo_root / "sigilzero" / "prompts" / doctrine_id.split("/")[-1] / version / filename,
            # Additional paths for containerized/workspace layouts
            self.repo_root / "app" / doctrine_id / version / filename,
            self.repo_root / "app" / "sigilzero" / doctrine_id / version / filename,
            self.repo_root / "app" / "sigilzero" / "prompts" / doctrine_id.split("/")[-1] / version / filename,
        ]
        
        doctrine_path = None
        for path in possible_paths:
            if path.exists():
                doctrine_path = path
                break
        
        if not doctrine_path:
            raise FileNotFoundError(
                f"Doctrine not found: {doctrine_id}/{version}/{filename}. "
                f"Tried: {[str(p) for p in possible_paths]}"
            )
        
        # Read and hash content
        content_bytes = doctrine_path.read_bytes()
        content = content_bytes.decode("utf-8")
        content_hash = sha256_bytes(content_bytes)
        
        # Create reference
        ref = DoctrineReference(
            doctrine_id=doctrine_id,
            version=version,
            sha256=content_hash,
            resolved_at=datetime.now(timezone.utc).isoformat(),
        )
        
        # Store resolved path as repo-relative POSIX path for determinism
        try:
            rel_path = doctrine_path.relative_to(self.repo_root)
            ref.resolved_path = rel_path.as_posix()  # Convert to forward slashes
        except ValueError:
            # If path is not under repo_root, omit resolved_path to avoid determinism drift
            pass
        
        return content, ref
    
    def resolve_doctrine_version(
        self,
        doctrine_id: str,
        version_hint: Optional[str] = None
    ) -> str:
        """Resolve doctrine version.
        
        Args:
            doctrine_id: Doctrine identifier
            version_hint: Optional version hint (default: use latest)
        
        Returns:
            Resolved version string
        """
        # For Phase 1.0, we use explicit versions
        # Future: could implement "latest" resolution
        if version_hint:
            return version_hint
        
        # Default to v1.0.0 if no hint provided
        return "v1.0.0"


def get_doctrine_loader(repo_root: str) -> DoctrineLoader:
    """Get a doctrine loader for the given repo root."""
    return DoctrineLoader(repo_root)
