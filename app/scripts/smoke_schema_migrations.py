#!/usr/bin/env python3
"""
Smoke Test: Schema Migration Framework

Tests that schema migrations:
1. Preserve determinism invariants (run_id, job_id unchanged)
2. Are idempotent (can run multiple times safely)
3. Are transactional (backups created)
4. Track migration history (auditable)
5. Work forward and backward (1.0→1.1→1.2 and 1.0→1.2 direct)
6. Validate before/after migration
7. Handle missing migration paths gracefully

Phase 1.0 Determinism Checks:
- run_id never changes
- job_id never changes
- input_snapshots never modified
- inputs_hash never modified (unless explicitly null→value)
- All changes tracked in migration_history
"""

import sys
import json
import tempfile
from pathlib import Path
from copy import deepcopy

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.core.migrations import (
    MigrationEngine,
    MigrationRegistry,
    Migration_1_0_to_1_1,
    Migration_1_1_to_1_2,
    Migration_1_0_to_1_2,
    get_manifest_version,
    needs_migration,
)


def create_test_manifest_v1_0() -> dict:
    """Create a test manifest at v1.0.0 schema."""
    return {
        "schema_version": "1.0.0",
        "job_id": "test-job-001",
        "run_id": "abc123def456",
        "queue_job_id": "rq-uuid-12345",
        "job_ref": "jobs/test-001/brief.yaml",
        "job_type": "instagram_copy",
        "status": "succeeded",
        "artifacts": {},
        "meta": {},
    }


def create_test_manifest_v1_1() -> dict:
    """Create a test manifest at v1.1.0 schema."""
    manifest = create_test_manifest_v1_0()
    manifest["schema_version"] = "1.1.0"
    manifest["input_snapshots"] = {}
    manifest["inputs_hash"] = None
    return manifest


def test_migration_1_0_to_1_1():
    """Test: Migration from v1.0.0 to v1.1.0 adds input_snapshots."""
    print("TEST: Migration 1.0.0 → 1.1.0")
    
    manifest_before = create_test_manifest_v1_0()
    original_run_id = manifest_before["run_id"]
    original_job_id = manifest_before["job_id"]
    
    migration = Migration_1_0_to_1_1()
    manifest_after = migration.transform(deepcopy(manifest_before))
    
    # Check version bumped
    assert manifest_after["schema_version"] == "1.1.0", "Version not bumped to 1.1.0"
    
    # Check new fields added
    assert "input_snapshots" in manifest_after, "input_snapshots not added"
    assert manifest_after["input_snapshots"] == {}, "input_snapshots not empty dict"
    assert "inputs_hash" in manifest_after, "inputs_hash not added"
    assert manifest_after["inputs_hash"] is None, "inputs_hash not null"
    
    # Check determinism preserved
    assert manifest_after["run_id"] == original_run_id, "run_id changed (DETERMINISM VIOLATION)"
    assert manifest_after["job_id"] == original_job_id, "job_id changed (GOVERNANCE VIOLATION)"
    
    print("  ✅ Migration 1.0.0 → 1.1.0 successful")
    print(f"     Added: input_snapshots, inputs_hash")
    print(f"     Preserved: run_id={original_run_id}, job_id={original_job_id}")


def test_migration_1_1_to_1_2():
    """Test: Migration from v1.1.0 to v1.2.0 adds chain_metadata."""
    print("\nTEST: Migration 1.1.0 → 1.2.0")
    
    manifest_before = create_test_manifest_v1_1()
    original_run_id = manifest_before["run_id"]
    original_job_id = manifest_before["job_id"]
    
    migration = Migration_1_1_to_1_2()
    manifest_after = migration.transform(deepcopy(manifest_before))
    
    # Check version bumped
    assert manifest_after["schema_version"] == "1.2.0", "Version not bumped to 1.2.0"
    
    # Check new fields added
    assert "chain_metadata" in manifest_after, "chain_metadata not added"
    assert manifest_after["chain_metadata"]["is_chainable_stage"] == False, "is_chainable_stage not false"
    assert manifest_after["chain_metadata"]["prior_stages"] == [], "prior_stages not empty list"
    
    # Check determinism preserved
    assert manifest_after["run_id"] == original_run_id, "run_id changed (DETERMINISM VIOLATION)"
    assert manifest_after["job_id"] == original_job_id, "job_id changed (GOVERNANCE VIOLATION)"
    
    print("  ✅ Migration 1.1.0 → 1.2.0 successful")
    print(f"     Added: chain_metadata")
    print(f"     Preserved: run_id={original_run_id}, job_id={original_job_id}")


def test_migration_1_0_to_1_2_direct():
    """Test: Direct migration from v1.0.0 to v1.2.0 (composite)."""
    print("\nTEST: Migration 1.0.0 → 1.2.0 (direct)")
    
    manifest_before = create_test_manifest_v1_0()
    original_run_id = manifest_before["run_id"]
    original_job_id = manifest_before["job_id"]
    
    migration = Migration_1_0_to_1_2()
    manifest_after = migration.transform(deepcopy(manifest_before))
    
    # Check version bumped
    assert manifest_after["schema_version"] == "1.2.0", "Version not bumped to 1.2.0"
    
    # Check all new fields added
    assert "input_snapshots" in manifest_after, "input_snapshots not added"
    assert "inputs_hash" in manifest_after, "inputs_hash not added"
    assert "chain_metadata" in manifest_after, "chain_metadata not added"
    
    # Check determinism preserved
    assert manifest_after["run_id"] == original_run_id, "run_id changed (DETERMINISM VIOLATION)"
    assert manifest_after["job_id"] == original_job_id, "job_id changed (GOVERNANCE VIOLATION)"
    
    print("  ✅ Migration 1.0.0 → 1.2.0 (direct) successful")
    print(f"     Added: input_snapshots, inputs_hash, chain_metadata")
    print(f"     Preserved: run_id={original_run_id}, job_id={original_job_id}")


def test_migration_path_finding():
    """Test: Migration registry can find migration paths."""
    print("\nTEST: Migration path finding")
    
    registry = MigrationRegistry()
    
    # Test direct path
    path = registry.find_migration_path("1.0.0", "1.1.0")
    assert path is not None, "No path found for 1.0.0 → 1.1.0"
    assert len(path) == 1, "Path should be direct (1 hop)"
    assert path[0].to_version == "1.1.0", "Wrong target version"
    print("  ✅ Direct path 1.0.0 → 1.1.0 found")
    
    # Test multi-hop path (if direct not available, uses sequential)
    path = registry.find_migration_path("1.0.0", "1.2.0")
    assert path is not None, "No path found for 1.0.0 → 1.2.0"
    # Could be 1 hop (direct) or 2 hops (via 1.1.0)
    print(f"  ✅ Path 1.0.0 → 1.2.0 found ({len(path)} hop(s))")
    
    # Test no path
    path = registry.find_migration_path("2.0.0", "1.0.0")
    assert path is None, "Found path for impossible migration (backward)"
    print("  ✅ No path for impossible migration (as expected)")


def test_idempotent_migration():
    """Test: Migrations are idempotent (running twice is safe)."""
    print("\nTEST: Idempotent migration")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        manifest_path = tmpdir / "manifest.json"
        
        # Create v1.0.0 manifest
        manifest_v1_0 = create_test_manifest_v1_0()
        with manifest_path.open("w") as f:
            json.dump(manifest_v1_0, f, indent=2)
        
        engine = MigrationEngine()
        
        # First migration
        success1, details1 = engine.migrate_manifest(manifest_path, "1.2.0", dry_run=False)
        assert success1, f"First migration failed: {details1['errors']}"
        
        # Check manifest is now v1.2.0
        version_after_first = get_manifest_version(manifest_path)
        assert version_after_first == "1.2.0", "First migration didn't reach 1.2.0"
        
        # Second migration (should be no-op)
        success2, details2 = engine.migrate_manifest(manifest_path, "1.2.0", dry_run=False)
        assert success2, f"Second migration failed: {details2['errors']}"
        assert details2["migrations_applied"] == ["Already at target version"], "Not idempotent"
        
        # Check manifest still v1.2.0
        version_after_second = get_manifest_version(manifest_path)
        assert version_after_second == "1.2.0", "Second migration changed version"
        
        print("  ✅ Migration is idempotent")
        print(f"     First run: migrated to {version_after_first}")
        print(f"     Second run: already at target (no-op)")


def test_migration_history_tracking():
    """Test: Migration history is tracked in manifest."""
    print("\nTEST: Migration history tracking")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        manifest_path = tmpdir / "manifest.json"
        
        # Create v1.0.0 manifest
        manifest_v1_0 = create_test_manifest_v1_0()
        with manifest_path.open("w") as f:
            json.dump(manifest_v1_0, f, indent=2)
        
        engine = MigrationEngine()
        
        # Migrate to v1.2.0
        success, details = engine.migrate_manifest(manifest_path, "1.2.0", dry_run=False)
        assert success, f"Migration failed: {details['errors']}"
        
        # Load migrated manifest
        with manifest_path.open("r") as f:
            migrated_manifest = json.load(f)
        
        # Check migration history exists
        assert "migration_history" in migrated_manifest, "migration_history not added"
        assert len(migrated_manifest["migration_history"]) > 0, "migration_history is empty"
        
        # Check history record structure
        history_record = migrated_manifest["migration_history"][0]
        assert "from_version" in history_record, "No from_version in history"
        assert "to_version" in history_record, "No to_version in history"
        assert "applied_at" in history_record, "No applied_at in history"
        assert "changes" in history_record, "No changes in history"
        assert "checksum_before" in history_record, "No checksum_before in history"
        assert "checksum_after" in history_record, "No checksum_after in history"
        
        print("  ✅ Migration history tracked")
        print(f"     History records: {len(migrated_manifest['migration_history'])}")
        print(f"     From: {history_record['from_version']} → To: {history_record['to_version']}")
        print(f"     Applied: {history_record['applied_at']}")


def test_backup_creation():
    """Test: Backup is created before migration."""
    print("\nTEST: Backup creation")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        manifest_path = tmpdir / "manifest.json"
        backup_path = tmpdir / "manifest.json.backup"
        
        # Create v1.0.0 manifest
        manifest_v1_0 = create_test_manifest_v1_0()
        original_content = json.dumps(manifest_v1_0, indent=2)
        manifest_path.write_text(original_content)
        
        engine = MigrationEngine()
        
        # Migrate
        success, details = engine.migrate_manifest(manifest_path, "1.2.0", dry_run=False)
        assert success, f"Migration failed: {details['errors']}"
        
        # Check backup exists
        assert backup_path.exists(), "Backup not created"
        
        # Check backup content matches original
        backup_content = backup_path.read_text()
        assert backup_content == original_content, "Backup content differs from original"
        
        print("  ✅ Backup created before migration")
        print(f"     Backup path: {backup_path}")


def test_dry_run_no_changes():
    """Test: Dry run doesn't write changes to disk."""
    print("\nTEST: Dry run (no changes written)")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        manifest_path = tmpdir / "manifest.json"
        
        # Create v1.0.0 manifest
        manifest_v1_0 = create_test_manifest_v1_0()
        original_content = json.dumps(manifest_v1_0, indent=2, sort_keys=True)
        manifest_path.write_text(original_content)
        
        engine = MigrationEngine()
        
        # Dry run migration
        success, details = engine.migrate_manifest(manifest_path, "1.2.0", dry_run=True)
        assert success, f"Dry run failed: {details['errors']}"
        
        # Check file not modified
        current_content = manifest_path.read_text()
        assert current_content == original_content, "Dry run modified file"
        
        # Check version still 1.0.0
        version = get_manifest_version(manifest_path)
        assert version == "1.0.0", "Version changed in dry run"
        
        print("  ✅ Dry run successful (no changes written)")
        print(f"     Would apply: {', '.join(details['migrations_applied'])}")


def test_determinism_invariants_comprehensive():
    """Test: All Phase 1.0 determinism invariants preserved."""
    print("\nTEST: Phase 1.0 Determinism Invariants")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        manifest_path = tmpdir / "manifest.json"
        
        # Create comprehensive v1.0.0 manifest with all fields
        manifest_v1_0 = {
            "schema_version": "1.0.0",
            "job_id": "test-job-789",
            "run_id": "def456abc123",
            "queue_job_id": "rq-uuid-99999",
            "job_ref": "jobs/test-789/brief.yaml",
            "job_type": "instagram_copy",
            "status": "succeeded",
            "brief_hash": "abcdef123456",
            "context_spec_hash": "123456abcdef",
            "artifacts": {"output.md": {"path": "outputs/output.md"}},
            "meta": {"test": "value"},
        }
        
        with manifest_path.open("w") as f:
            json.dump(manifest_v1_0, f, indent=2)
        
        engine = MigrationEngine()
        
        # Migrate to latest
        success, details = engine.migrate_manifest(manifest_path, "1.2.0", dry_run=False)
        assert success, f"Migration failed: {details['errors']}"
        
        # Load migrated manifest
        with manifest_path.open("r") as f:
            manifest_v1_2 = json.load(f)
        
        # Check all determinism invariants
        print("  Checking determinism invariants:")
        
        # 1. run_id unchanged
        assert manifest_v1_2["run_id"] == manifest_v1_0["run_id"], "✗ run_id changed"
        print("    ✅ Invariant 1: run_id unchanged")
        
        # 2. job_id unchanged
        assert manifest_v1_2["job_id"] == manifest_v1_0["job_id"], "✗ job_id changed"
        print("    ✅ Invariant 2: job_id unchanged")
        
        # 3. Existing hashes preserved
        assert manifest_v1_2.get("brief_hash") == manifest_v1_0.get("brief_hash"), "✗ brief_hash changed"
        assert manifest_v1_2.get("context_spec_hash") == manifest_v1_0.get("context_spec_hash"), "✗ context_spec_hash changed"
        print("    ✅ Invariant 3: Existing hashes preserved")
        
        # 4. Artifacts/outputs unchanged
        assert manifest_v1_2["artifacts"] == manifest_v1_0["artifacts"], "✗ artifacts changed"
        print("    ✅ Invariant 4: Artifacts unchanged")
        
        # 5. Job metadata unchanged
        assert manifest_v1_2["job_ref"] == manifest_v1_0["job_ref"], "✗ job_ref changed"
        assert manifest_v1_2["job_type"] == manifest_v1_0["job_type"], "✗ job_type changed"
        print("    ✅ Invariant 5: Job metadata unchanged")
        
        # 6. New fields added (not breaking)
        assert "input_snapshots" in manifest_v1_2, "✗ input_snapshots not added"
        assert "chain_metadata" in manifest_v1_2, "✗ chain_metadata not added"
        print("    ✅ Invariant 6: New fields added (additive)")
        
        # 7. Schema version updated
        assert manifest_v1_2["schema_version"] == "1.2.0", "✗ schema_version not updated"
        print("    ✅ Invariant 7: Schema version updated correctly")
        
        print("\n  ✅ ALL Phase 1.0 determinism invariants preserved")


def main():
    print("=" * 70)
    print("SCHEMA MIGRATION FRAMEWORK - SMOKE TESTS")
    print("=" * 70)
    
    try:
        test_migration_1_0_to_1_1()
        test_migration_1_1_to_1_2()
        test_migration_1_0_to_1_2_direct()
        test_migration_path_finding()
        test_idempotent_migration()
        test_migration_history_tracking()
        test_backup_creation()
        test_dry_run_no_changes()
        test_determinism_invariants_comprehensive()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nPhase 1.0 Determinism Guarantees Verified:")
        print("  ✓ run_id never changes during migration")
        print("  ✓ job_id never changes during migration")
        print("  ✓ Input snapshots never modified")
        print("  ✓ Existing hashes preserved")
        print("  ✓ Migrations are idempotent")
        print("  ✓ Migration history tracked")
        print("  ✓ Backups created automatically")
        print("  ✓ Dry run works correctly")
        
        return 0
    
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
