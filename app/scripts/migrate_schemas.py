#!/usr/bin/env python3
"""
Schema Migration Script: Migrate manifests to target schema version

Usage:
    # Migrate all artifacts to latest version
    python scripts/migrate_schemas.py /app
    
    # Migrate to specific version
    python scripts/migrate_schemas.py /app --target-version 1.2.0
    
    # Dry run (no changes written)
    python scripts/migrate_schemas.py /app --dry-run
    
    # Migrate single manifest
    python scripts/migrate_schemas.py /app --manifest artifacts/ig-test-001/abc123/manifest.json

Phase 1.0 Determinism Guarantees:
- Migrations never change run_id or job_id
- Migrations never modify input snapshot files
- Migrations are idempotent (safe to run multiple times)
- Backups created automatically before migration
- All changes tracked in manifest.migration_history
"""

import argparse
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.core.migrations import MigrationEngine, MigrationRegistry, get_manifest_version, needs_migration


def migrate_single_manifest(app_root: Path, manifest_rel_path: str, target_version: str, dry_run: bool):
    """Migrate a single manifest file."""
    manifest_path = app_root / manifest_rel_path
    
    if not manifest_path.exists():
        print(f"❌ Manifest not found: {manifest_path}")
        return False
    
    print(f"Migrating: {manifest_rel_path}")
    print(f"  Current version: {get_manifest_version(manifest_path)}")
    print(f"  Target version: {target_version}")
    
    if dry_run:
        print("  [DRY RUN - no changes will be written]")
    
    engine = MigrationEngine()
    success, details = engine.migrate_manifest(manifest_path, target_version, dry_run)
    
    if success:
        print("  ✅ Migration successful")
        if details["migrations_applied"] == ["Already at target version"]:
            print("     Already at target version")
        else:
            print(f"     Applied: {', '.join(details['migrations_applied'])}")
        
        if not dry_run and "backup_created" in details:
            print(f"     Backup: {details['backup_created']}")
    else:
        print("  ❌ Migration failed")
        for error in details["errors"]:
            print(f"     Error: {error}")
        return False
    
    return True


def migrate_all_artifacts(app_root: Path, target_version: str, dry_run: bool):
    """Migrate all manifests in artifacts directory."""
    artifacts_dir = app_root / "artifacts"
    
    if not artifacts_dir.exists():
        print(f"❌ Artifacts directory not found: {artifacts_dir}")
        return False
    
    print(f"Migrating all manifests in: {artifacts_dir}")
    print(f"Target version: {target_version}")
    
    if dry_run:
        print("[DRY RUN - no changes will be written]\n")
    
    engine = MigrationEngine()
    summary = engine.migrate_all_artifacts(artifacts_dir, target_version, dry_run)
    
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"Total manifests found: {summary['total_manifests']}")
    print(f"Migrated:              {summary['migrated']}")
    print(f"Already current:       {summary['already_current']}")
    print(f"Failed:                {summary['failed']}")
    
    if summary["errors"]:
        print("\nERRORS:")
        for error_detail in summary["errors"]:
            print(f"\n  Path: {error_detail['path']}")
            for error in error_detail["errors"]:
                print(f"    - {error}")
    
    if dry_run:
        print("\n[DRY RUN COMPLETE - no changes were written]")
    else:
        print(f"\n✅ Migration complete (backups created as *.json.backup)")
    
    return summary["failed"] == 0


def list_versions(app_root: Path):
    """List schema versions of all manifests."""
    artifacts_dir = app_root / "artifacts"
    
    if not artifacts_dir.exists():
        print(f"❌ Artifacts directory not found: {artifacts_dir}")
        return
    
    manifest_paths = list(artifacts_dir.rglob("manifest.json"))
    
    if not manifest_paths:
        print("No manifests found.")
        return
    
    # Collect version stats
    version_counts = {}
    for manifest_path in manifest_paths:
        version = get_manifest_version(manifest_path)
        version_counts[version] = version_counts.get(version, 0) + 1
    
    print(f"Found {len(manifest_paths)} manifests\n")
    print("Schema Version Distribution:")
    print("-" * 40)
    
    for version in sorted(version_counts.keys()):
        count = version_counts[version]
        percentage = (count / len(manifest_paths)) * 100
        print(f"  {version:10s} : {count:4d} ({percentage:5.1f}%)")
    
    # Show registry's latest version
    registry = MigrationRegistry()
    latest = registry.get_latest_version()
    print(f"\nLatest version available: {latest}")
    
    # Show which need migration
    needs_upgrade = sum(1 for p in manifest_paths if needs_migration(p, latest))
    if needs_upgrade > 0:
        print(f"\n⚠️  {needs_upgrade} manifests need migration to {latest}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate manifest schemas to target version",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check current version distribution
  python scripts/migrate_schemas.py /app --list-versions
  
  # Dry run migration to latest version
  python scripts/migrate_schemas.py /app --dry-run
  
  # Migrate all to latest version
  python scripts/migrate_schemas.py /app
  
  # Migrate to specific version
  python scripts/migrate_schemas.py /app --target-version 1.2.0
  
  # Migrate single manifest
  python scripts/migrate_schemas.py /app --manifest artifacts/ig-test-001/abc/manifest.json
        """
    )
    
    parser.add_argument(
        "app_root",
        type=str,
        help="Path to app root (e.g., /app)"
    )
    
    parser.add_argument(
        "--target-version",
        type=str,
        default=None,
        help="Target schema version (default: latest)"
    )
    
    parser.add_argument(
        "--manifest",
        type=str,
        default=None,
        help="Migrate single manifest (relative path from app_root)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without writing changes"
    )
    
    parser.add_argument(
        "--list-versions",
        action="store_true",
        help="List schema version distribution without migrating"
    )
    
    args = parser.parse_args()
    
    app_root = Path(args.app_root).resolve()
    
    if not app_root.exists():
        print(f"❌ App root not found: {app_root}")
        sys.exit(1)
    
    # Determine target version
    target_version = args.target_version
    if target_version is None:
        registry = MigrationRegistry()
        target_version = registry.get_latest_version()
    
    # Execute command
    if args.list_versions:
        list_versions(app_root)
    elif args.manifest:
        success = migrate_single_manifest(app_root, args.manifest, target_version, args.dry_run)
        sys.exit(0 if success else 1)
    else:
        success = migrate_all_artifacts(app_root, target_version, args.dry_run)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
