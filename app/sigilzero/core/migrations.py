"""
Schema Migration Framework: Phase 1.0 Determinism-Preserving Migrations

This module provides schema versioning and migration capabilities that preserve
all 7 Phase 1.0 determinism invariants:

1. Canonical Input Snapshots - Migrations never modify input snapshots
2. Deterministic run_id - run_id never changes during migration
3. Governance job_id - job_id never changes during migration
4. Doctrine as Hashed Input - Doctrine snapshots immutable
5. Filesystem Authoritative - Migrations operate on filesystem first
6. No Silent Drift - All changes tracked in migration_history
7. Backward Compatibility - Old clients can read new schemas

Migration Philosophy:
- Manifests are migrated IN-PLACE on disk (filesystem is source of truth)
- Database indices are REBUILT from migrated artifacts (DB is secondary)
- Migrations are IDEMPOTENT (can run multiple times safely)
- Migrations are ADDITIVE (add fields, never remove or modify existing data)
- Migration history is AUDITABLE (migration_history tracks all changes)

Schema Version Format: MAJOR.MINOR.PATCH (semver)
- MAJOR: Breaking changes (rare; requires explicit migration strategy)
- MINOR: Additive changes (new optional fields, new features)
- PATCH: Bug fixes, clarifications (no schema changes)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime
from packaging import version

from .hashing import sha256_bytes


# -----------------------------
# Migration Types
# -----------------------------

class MigrationRecord(dict):
    """Record of a single migration applied to a manifest.
    
    Stored in manifest.migration_history[] for audit trail.
    """
    from_version: str
    to_version: str
    applied_at: str  # ISO 8601 timestamp
    changes: List[str]  # Human-readable list of changes made
    checksum_before: str  # SHA256 of manifest before migration
    checksum_after: str  # SHA256 of manifest after migration


class Migration:
    """Base class for schema migrations.
    
    Each migration defines:
    - from_version: Starting schema version
    - to_version: Target schema version
    - transform(): Function that applies migration to manifest data
    """
    
    def __init__(self, from_version: str, to_version: str):
        self.from_version = from_version
        self.to_version = to_version
        self.changes: List[str] = []
    
    def transform(self, manifest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply migration transformation to manifest data.
        
        Args:
            manifest_data: Raw dictionary loaded from manifest.json
        
        Returns:
            Transformed manifest data with new schema version
        
        CRITICAL: This method must be PURE - no side effects, no I/O.
        All filesystem operations handled by MigrationEngine.
        """
        raise NotImplementedError("Subclasses must implement transform()")
    
    def validate_before(self, manifest_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate manifest is eligible for this migration.
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        current_version = manifest_data.get("schema_version", "1.0.0")
        
        if current_version != self.from_version:
            errors.append(f"Expected schema_version {self.from_version}, got {current_version}")
        
        return len(errors) == 0, errors
    
    def validate_after(self, manifest_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate migrated manifest meets target schema.
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        new_version = manifest_data.get("schema_version")
        
        if new_version != self.to_version:
            errors.append(f"Expected schema_version {self.to_version} after migration, got {new_version}")
        
        return len(errors) == 0, errors


# -----------------------------
# Concrete Migrations
# -----------------------------

class Migration_1_0_to_1_1(Migration):
    """Migration from v1.0.0 to v1.1.0: Add input_snapshots field.
    
    Phase 1.0 Context:
    - v1.0.0: No input_snapshots field (legacy instagram_copy)
    - v1.1.0: Adds input_snapshots dict with snapshot metadata
    
    Changes:
    - Add input_snapshots: {} (empty for now; backfill via separate script)
    - Add inputs_hash: null (will be computed if snapshots exist)
    - Bump schema_version to 1.1.0
    
    Determinism Impact: NONE
    - Does not change run_id or job_id
    - Does not modify existing input snapshot files
    - Additive change only
    """
    
    def __init__(self):
        super().__init__(from_version="1.0.0", to_version="1.1.0")
        self.changes = [
            "Add input_snapshots field (empty dict)",
            "Add inputs_hash field (null)",
            "Bump schema_version to 1.1.0",
        ]
    
    def transform(self, manifest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add input_snapshots structure to v1.0.0 manifest."""
        # Add new fields
        manifest_data["input_snapshots"] = {}
        manifest_data["inputs_hash"] = None
        
        # Bump version
        manifest_data["schema_version"] = "1.1.0"
        
        return manifest_data


class Migration_1_1_to_1_2(Migration):
    """Migration from v1.1.0 to v1.2.0: Add chain_metadata for Phase 8.
    
    Phase 8 Context:
    - v1.1.0: No chainable pipeline support
    - v1.2.0: Adds chain_metadata for pipeline composition
    
    Changes:
    - Add chain_metadata.is_chainable_stage: false (default for non-chainable)
    - Add chain_metadata.prior_stages: [] (empty for non-chainable)
    - Bump schema_version to 1.2.0
    
    Determinism Impact: NONE
    - Does not change run_id or job_id
    - Does not modify existing snapshot files
    - Additive change only (default is_chainable_stage=false)
    """
    
    def __init__(self):
        super().__init__(from_version="1.1.0", to_version="1.2.0")
        self.changes = [
            "Add chain_metadata.is_chainable_stage (false)",
            "Add chain_metadata.prior_stages ([])",
            "Bump schema_version to 1.2.0",
        ]
    
    def transform(self, manifest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add chain_metadata structure to v1.1.0 manifest."""
        # Add chain metadata with defaults
        manifest_data["chain_metadata"] = {
            "is_chainable_stage": False,
            "prior_stages": [],
        }
        
        # Bump version
        manifest_data["schema_version"] = "1.2.0"
        
        return manifest_data


class Migration_1_0_to_1_2(Migration):
    """Direct migration from v1.0.0 to v1.2.0 (skips v1.1.0).
    
    This is a composite migration that applies both 1.0→1.1 and 1.1→1.2 changes
    in a single operation for efficiency.
    
    Changes:
    - Add input_snapshots: {}
    - Add inputs_hash: null
    - Add chain_metadata with defaults
    - Bump schema_version to 1.2.0
    """
    
    def __init__(self):
        super().__init__(from_version="1.0.0", to_version="1.2.0")
        self.changes = [
            "Add input_snapshots field (empty dict)",
            "Add inputs_hash field (null)",
            "Add chain_metadata.is_chainable_stage (false)",
            "Add chain_metadata.prior_stages ([])",
            "Bump schema_version to 1.2.0",
        ]
    
    def transform(self, manifest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply composite migration to v1.0.0 manifest."""
        # Add input snapshot fields
        manifest_data["input_snapshots"] = {}
        manifest_data["inputs_hash"] = None
        
        # Add chain metadata
        manifest_data["chain_metadata"] = {
            "is_chainable_stage": False,
            "prior_stages": [],
        }
        
        # Bump to latest version
        manifest_data["schema_version"] = "1.2.0"
        
        return manifest_data


# -----------------------------
# Migration Registry
# -----------------------------

class MigrationRegistry:
    """Registry of all available migrations.
    
    Maps (from_version, to_version) pairs to Migration instances.
    Provides path-finding for multi-hop migrations.
    """
    
    def __init__(self):
        self._migrations: Dict[Tuple[str, str], Migration] = {}
        self._register_builtin_migrations()
    
    def _register_builtin_migrations(self):
        """Register all built-in migrations."""
        migrations = [
            Migration_1_0_to_1_1(),
            Migration_1_1_to_1_2(),
            Migration_1_0_to_1_2(),  # Direct path for efficiency
        ]
        
        for migration in migrations:
            self.register(migration)
    
    def register(self, migration: Migration):
        """Register a migration in the registry."""
        key = (migration.from_version, migration.to_version)
        self._migrations[key] = migration
    
    def get_migration(self, from_version: str, to_version: str) -> Optional[Migration]:
        """Get a migration for a specific version pair.
        
        Returns direct migration if available, otherwise None.
        Use find_migration_path() for multi-hop migrations.
        """
        key = (from_version, to_version)
        return self._migrations.get(key)
    
    def find_migration_path(self, from_version: str, to_version: str) -> Optional[List[Migration]]:
        """Find a path of migrations from from_version to to_version.
        
        Returns:
            List of Migration instances to apply in sequence, or None if no path exists.
        
        Algorithm: Breadth-first search for shortest path.
        Prefers direct migrations over multi-hop.
        """
        # Check for direct migration first
        direct = self.get_migration(from_version, to_version)
        if direct:
            return [direct]
        
        # BFS to find shortest path
        from collections import deque
        
        queue = deque([(from_version, [])])
        visited = {from_version}
        
        while queue:
            current_version, path = queue.popleft()
            
            # Find all migrations from current_version
            for (from_v, to_v), migration in self._migrations.items():
                if from_v != current_version or to_v in visited:
                    continue
                
                new_path = path + [migration]
                
                if to_v == to_version:
                    return new_path
                
                visited.add(to_v)
                queue.append((to_v, new_path))
        
        return None  # No path found
    
    def get_latest_version(self) -> str:
        """Get the latest schema version available in registry."""
        versions = set()
        for from_v, to_v in self._migrations.keys():
            versions.add(from_v)
            versions.add(to_v)
        
        if not versions:
            return "1.0.0"
        
        return str(max(versions, key=lambda v: version.parse(v)))


# -----------------------------
# Migration Engine
# -----------------------------

class MigrationEngine:
    """Engine for applying migrations to manifest files.
    
    Phase 1.0 Determinism Guarantees:
    - Migrations are filesystem-first (manifest.json updated on disk)
    - Migrations are idempotent (safe to run multiple times)
    - Migrations are auditable (migration_history tracks all changes)
    - Migrations never modify run_id, job_id, or input snapshots
    - Migrations are transactional (backup created before applying)
    """
    
    def __init__(self, registry: Optional[MigrationRegistry] = None):
        self.registry = registry or MigrationRegistry()
    
    def migrate_manifest(
        self,
        manifest_path: Path,
        target_version: Optional[str] = None,
        dry_run: bool = False,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Migrate a single manifest to target version.
        
        Args:
            manifest_path: Path to manifest.json file
            target_version: Target schema version (default: latest)
            dry_run: If True, don't write changes to disk
        
        Returns:
            (success, details_dict)
        
        Details dict contains:
        - current_version: Version before migration
        - target_version: Version after migration
        - migrations_applied: List of migration descriptions
        - errors: List of errors if migration failed
        """
        details = {
            "manifest_path": str(manifest_path),
            "current_version": None,
            "target_version": target_version,
            "migrations_applied": [],
            "errors": [],
        }
        
        try:
            # Load manifest
            with manifest_path.open("r") as f:
                manifest_data = json.load(f)
            
            current_version = manifest_data.get("schema_version", "1.0.0")
            details["current_version"] = current_version
            
            # Determine target version
            if target_version is None:
                target_version = self.registry.get_latest_version()
                details["target_version"] = target_version
            
            # Check if already at target version
            if current_version == target_version:
                details["migrations_applied"] = ["Already at target version"]
                return True, details
            
            # Find migration path
            migration_path = self.registry.find_migration_path(current_version, target_version)
            
            if migration_path is None:
                details["errors"].append(f"No migration path from {current_version} to {target_version}")
                return False, details
            
            # Compute checksum before migration
            checksum_before = sha256_bytes(json.dumps(manifest_data, sort_keys=True).encode())
            
            # Apply migrations in sequence
            for migration in migration_path:
                # Validate before
                valid, errors = migration.validate_before(manifest_data)
                if not valid:
                    details["errors"].extend(errors)
                    return False, details
                
                # Apply transformation
                manifest_data = migration.transform(manifest_data)
                
                # Validate after
                valid, errors = migration.validate_after(manifest_data)
                if not valid:
                    details["errors"].extend(errors)
                    return False, details
                
                # Record migration
                details["migrations_applied"].append(f"{migration.from_version} → {migration.to_version}")
            
            # Compute checksum after migration
            checksum_after = sha256_bytes(json.dumps(manifest_data, sort_keys=True).encode())
            
            # Add migration history record
            if "migration_history" not in manifest_data:
                manifest_data["migration_history"] = []
            
            manifest_data["migration_history"].append({
                "from_version": current_version,
                "to_version": target_version,
                "applied_at": datetime.utcnow().isoformat() + "Z",
                "changes": [m.changes for m in migration_path],
                "checksum_before": checksum_before,
                "checksum_after": checksum_after,
            })
            
            # Write back to disk (unless dry run)
            if not dry_run:
                # Create backup
                backup_path = manifest_path.with_suffix(".json.backup")
                backup_path.write_text(manifest_path.read_text())
                
                # Write migrated manifest
                with manifest_path.open("w") as f:
                    json.dump(manifest_data, f, indent=2, sort_keys=True, ensure_ascii=False)
                
                details["backup_created"] = str(backup_path)
            
            return True, details
        
        except Exception as e:
            details["errors"].append(f"Migration failed: {e}")
            return False, details
    
    def migrate_all_artifacts(
        self,
        artifacts_dir: Path,
        target_version: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Migrate all manifests in artifacts directory.
        
        Args:
            artifacts_dir: Path to artifacts/ directory
            target_version: Target schema version (default: latest)
            dry_run: If True, don't write changes to disk
        
        Returns:
            Summary dict with success/failure counts and details
        """
        summary = {
            "total_manifests": 0,
            "migrated": 0,
            "already_current": 0,
            "failed": 0,
            "errors": [],
        }
        
        # Find all manifest.json files
        manifest_paths = list(artifacts_dir.rglob("manifest.json"))
        summary["total_manifests"] = len(manifest_paths)
        
        for manifest_path in manifest_paths:
            success, details = self.migrate_manifest(manifest_path, target_version, dry_run)
            
            if success:
                if details["migrations_applied"] == ["Already at target version"]:
                    summary["already_current"] += 1
                else:
                    summary["migrated"] += 1
            else:
                summary["failed"] += 1
                summary["errors"].append({
                    "path": str(manifest_path),
                    "errors": details["errors"],
                })
        
        return summary


# -----------------------------
# Utility Functions
# -----------------------------

def get_manifest_version(manifest_path: Path) -> str:
    """Get schema version from a manifest file.
    
    Returns:
        Schema version string (e.g., "1.2.0"), defaults to "1.0.0" if not found.
    """
    try:
        with manifest_path.open("r") as f:
            manifest_data = json.load(f)
        return manifest_data.get("schema_version", "1.0.0")
    except Exception:
        return "1.0.0"


def needs_migration(manifest_path: Path, target_version: str) -> bool:
    """Check if a manifest needs migration to target version.
    
    Args:
        manifest_path: Path to manifest.json
        target_version: Target schema version
    
    Returns:
        True if migration needed, False if already at target version
    """
    current_version = get_manifest_version(manifest_path)
    return current_version != target_version
