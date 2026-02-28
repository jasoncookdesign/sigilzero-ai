#!/usr/bin/env python3
"""Phase 1.0 Determinism Smoke Tests

Validates that the determinism guardrails are working correctly:
1. Same inputs => same inputs_hash => same run_id
2. Idempotent replay returns existing run without creating duplicates
3. No orphaned temp directories after execution
4. Canonical JSON snapshots are byte-stable
"""

import json
import os
import shutil
import sys
import difflib
from pathlib import Path
from typing import Dict, Any

# Add app directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.pipelines.phase0_instagram_copy import execute_instagram_copy_pipeline
import sigilzero.pipelines.phase0_instagram_copy as pipeline_module
from sigilzero.core.hashing import sha256_bytes, compute_inputs_hash


def cleanup_test_artifacts(repo_root: str, run_ids: list[str], job_id: str | None = None) -> None:
    """Clean up test run directories.
    
    Note: artifacts/runs/.tmp directory is preserved but its contents are cleaned.
    This maintains the invariant that ".tmp exists but is empty after success".
    """
    artifacts_root = Path(repo_root) / "artifacts"
    runs_dir = artifacts_root / "runs"
    job_root = artifacts_root / job_id if job_id else None

    for run_id in run_ids:
        # Canonical location: artifacts/<job_id>/<run_id>
        if job_root is not None:
            canonical_run_dir = job_root / run_id
            if canonical_run_dir.exists():
                shutil.rmtree(canonical_run_dir)

        # Legacy compatibility location: artifacts/runs/<run_id>
        legacy_run_dir = runs_dir / run_id
        if legacy_run_dir.is_symlink() or legacy_run_dir.is_file():
            legacy_run_dir.unlink()
        elif legacy_run_dir.exists():
            shutil.rmtree(legacy_run_dir)
    
    # Clean .tmp contents but preserve directory
    for tmp_dir in [runs_dir / ".tmp", (job_root / ".tmp") if job_root else None]:
        if tmp_dir is None or not tmp_dir.exists():
            continue
        for item in tmp_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()


def validate_no_temp_dirs(repo_root: str, job_id: str) -> bool:
    """Ensure no orphaned temp directories exist."""
    artifacts_root = Path(repo_root) / "artifacts"
    runs_dir = artifacts_root / "runs"
    job_root = artifacts_root / job_id

    # Check both legacy and canonical .tmp directories
    for tmp_dir in [runs_dir / ".tmp", job_root / ".tmp"]:
        if tmp_dir.exists():
            temp_contents = [p for p in tmp_dir.iterdir() if p.name.startswith("tmp-")]
            if temp_contents:
                print(f"✗ Found orphaned temp directories in {tmp_dir}: {temp_contents}")
                return False
    
    # Check for old-style staging dirs (shouldn't exist with new code)
    staging_dirs = [d for d in runs_dir.iterdir() if d.name.startswith("staging-")] if runs_dir.exists() else []
    if staging_dirs:
        print(f"✗ Found orphaned staging directories: {staging_dirs}")
        return False
    
    return True


def validate_canonical_json(snapshot_path: Path) -> bool:
    """Validate that JSON snapshot is canonical (sorted keys, stable formatting)."""
    if not snapshot_path.exists():
        print(f"✗ Snapshot {snapshot_path} does not exist")
        return False
    
    # Read and re-encode to verify canonicalization
    with snapshot_path.open("r") as f:
        data = json.load(f)
    
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)
    if not canonical.endswith("\n"):
        canonical += "\n"
    
    actual = snapshot_path.read_text(encoding="utf-8")
    
    if actual != canonical:
        print(f"✗ Snapshot {snapshot_path} is not canonical")
        print(f"  Expected length: {len(canonical)}, actual: {len(actual)}")
        return False
    
    return True


def normalized_manifest_bytes(manifest: dict) -> bytes:
    """Return deterministic byte representation of manifest excluding volatile runtime fields."""
    m = dict(manifest)
    m.pop("started_at", None)
    m.pop("finished_at", None)
    m.pop("queue_job_id", None)
    m.pop("langfuse_trace_id", None)
    doctrine = dict(m.get("doctrine") or {})
    doctrine.pop("resolved_at", None)
    m["doctrine"] = doctrine
    return (json.dumps(m, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def run_smoke_tests():
    """Run Phase 1.0 determinism smoke tests."""
    repo_root = os.getenv("SIGILZERO_REPO_ROOT", "/app")
    job_ref = "jobs/ig-test-001/brief.yaml"
    
    print("=" * 60)
    print("Phase 1.0 Determinism Smoke Tests")
    print("=" * 60)
    print(f"\nEnvironment:")
    print(f"  repo_root: {repo_root}")
    print(f"  cwd: {os.getcwd()}")
    print()
    
    # Track run_ids for cleanup
    cleanup_ids = []
    cleanup_job_id: str | None = None
    
    try:
        # Test 1: First execution
        print("\n[Test 1] First execution with identical inputs")
        result1 = execute_instagram_copy_pipeline(repo_root, job_ref, params={})
        run_id1 = result1["run_id"]
        cleanup_ids.append(run_id1)
        print(f"✓ First execution completed: run_id={run_id1}")
        
        # Validate manifest
        run_dir1 = Path(result1["artifact_dir"])
        manifest_path1 = run_dir1 / "manifest.json"
        with manifest_path1.open("r") as f:
            manifest1 = json.load(f)

        cleanup_job_id = manifest1.get("job_id")
        if not cleanup_job_id:
            print("✗ Missing job_id in manifest")
            return False

        # Validate canonical artifact layout: artifacts/<job_id>/<run_id>
        expected_run_dir = Path(repo_root) / "artifacts" / cleanup_job_id / run_id1
        if run_dir1.resolve() != expected_run_dir.resolve():
            print(f"✗ Run directory layout mismatch")
            print(f"  Expected: {expected_run_dir}")
            print(f"  Actual:   {run_dir1}")
            return False
        print(f"✓ Canonical artifact layout verified: artifacts/{cleanup_job_id}/{run_id1}")
        
        inputs_hash1 = manifest1.get("inputs_hash")
        if not inputs_hash1:
            print("✗ First manifest missing inputs_hash")
            return False
        print(f"✓ First execution inputs_hash: {inputs_hash1}")
        print(f"  Full run_id: {run_id1}")
        manifest_bytes_before_replay = manifest_path1.read_bytes()
        
        # Log doctrine resolution (proof of in-repo versioning)
        doctrine_info = manifest1.get("doctrine", {})
        if doctrine_info:
            print(f"  Doctrine:")
            print(f"    ID: {doctrine_info.get('doctrine_id')}")
            print(f"    Version: {doctrine_info.get('version')}")
            if "resolved_path" in doctrine_info:
                resolved_path = doctrine_info['resolved_path']
                print(f"    Resolved path (repo-relative): {resolved_path}")
                if Path(resolved_path).is_absolute():
                    print("    ✗ WARNING: doctrine resolved_path must not be absolute")
                    return False
                if ".." in Path(resolved_path).parts:
                    print("    ✗ WARNING: doctrine resolved_path must not contain '..' segments")
                    return False
                # Verify it's actually repo-relative and in-repo
                full_doctrine_path = Path(repo_root) / resolved_path
                if full_doctrine_path.exists():
                    print(f"    ✓ File verified in repo at: {full_doctrine_path}")
                else:
                    print(f"    ✗ WARNING: resolved_path points to non-existent file")
        
        # Validate canonical snapshots
        print("\n[Test 2] Validate canonical JSON snapshots")
        snapshots = [
            "inputs/brief.resolved.json",
            "inputs/context.resolved.json",
            "inputs/model_config.json",
            "inputs/doctrine.resolved.json",
        ]
        for snapshot_rel in snapshots:
            snapshot_path = run_dir1 / snapshot_rel
            if not validate_canonical_json(snapshot_path):
                return False
        print(f"✓ All {len(snapshots)} snapshots are canonical")
        
        # Test 3: Idempotent replay (same inputs)
        print("\n[Test 3] Idempotent replay with identical inputs")
        result2 = execute_instagram_copy_pipeline(repo_root, job_ref, params={})
        run_id2 = result2["run_id"]
        
        if run_id2 != run_id1:
            print(f"✗ Idempotent replay failed: run_id changed from {run_id1} to {run_id2}")
            cleanup_ids.append(run_id2)
            return False
        
        if not result2.get("idempotent_replay"):
            print("✗ Idempotent replay not detected (expected flag in result)")
            return False
        
        print(f"✓ Idempotent replay successful: same run_id={run_id2}")

        # manifest bytes should remain byte-identical on idempotent replay
        manifest_bytes_after_replay = manifest_path1.read_bytes()
        if manifest_bytes_after_replay != manifest_bytes_before_replay:
            print("✗ Manifest bytes changed across idempotent replay")
            return False
        print("✓ Manifest bytes are identical across idempotent replay")

        # queue_job_id must never influence run_id
        result2b = execute_instagram_copy_pipeline(repo_root, job_ref, params={"queue_job_id": "queue-test-123"})
        if result2b["run_id"] != run_id1:
            print("✗ queue_job_id influenced run_id")
            return False
        print("✓ queue_job_id does not influence run_id")
        
        # Test 4: Validate inputs_hash consistency
        print("\n[Test 4] Validate inputs_hash determinism")
        manifest_path2 = Path(result2["artifact_dir"]) / "manifest.json"
        with manifest_path2.open("r") as f:
            manifest2 = json.load(f)
        
        inputs_hash2 = manifest2.get("inputs_hash")
        if inputs_hash2 != inputs_hash1:
            print(f"✗ inputs_hash changed: {inputs_hash1} != {inputs_hash2}")
            return False
        print(f"✓ inputs_hash stable across replay: {inputs_hash2}")
        
        # Test 5: Validate inputs_hash derived from snapshot file bytes
        print("\n[Test 5] Validate inputs_hash derived ONLY from snapshot file bytes")
        # Recompute snapshot hashes from on-disk files
        snapshot_files = {
            "brief": run_dir1 / "inputs" / "brief.resolved.json",
            "context": run_dir1 / "inputs" / "context.resolved.json",
            "model_config": run_dir1 / "inputs" / "model_config.json",
            "doctrine": run_dir1 / "inputs" / "doctrine.resolved.json",
        }
        recomputed_snapshot_hashes = {}
        for name, path in snapshot_files.items():
            if not path.exists():
                print(f"✗ Snapshot file missing: {path}")
                return False
            snapshot_bytes = path.read_bytes()
            snapshot_hash = sha256_bytes(snapshot_bytes)
            recomputed_snapshot_hashes[name] = snapshot_hash
        
        # Recompute inputs_hash from snapshot hashes
        recomputed_inputs_hash = compute_inputs_hash(recomputed_snapshot_hashes)
        if recomputed_inputs_hash != inputs_hash1:
            print(f"✗ Recomputed inputs_hash does not match manifest")
            print(f"  Manifest:    {inputs_hash1}")
            print(f"  Recomputed:  {recomputed_inputs_hash}")
            return False
        print(f"✓ inputs_hash correctly derived from snapshot file bytes")
        print(f"  Verified: {recomputed_inputs_hash}")
        
        # Test 6: Validate run_id derivation
        print("\n[Test 6] Validate run_id derived from inputs_hash")
        # run_id should be first 32 hex chars of inputs_hash
        expected_prefix = inputs_hash1.replace("sha256:", "")[:32]
        if not run_id1.startswith(expected_prefix):
            print(f"✗ run_id {run_id1} does not match inputs_hash prefix {expected_prefix}")
            return False
        print(f"✓ run_id correctly derived from inputs_hash")
        
        # Test 7: Validate no orphaned temp dirs
        print("\n[Test 7] Validate no orphaned temp directories")
        if not validate_no_temp_dirs(repo_root, cleanup_job_id):
            return False
        print("✓ No orphaned temp or staging directories")
        
        # Test 8: Validate only ONE canonical run directory exists
        print("\n[Test 8] Validate single canonical run directory")
        runs_dir = Path(repo_root) / "artifacts" / cleanup_job_id
        
        # Determine which run_id should exist based on inputs_hash
        base_run_id = run_id1.split("-")[0]  # Get base (without suffix)
        base_dir = runs_dir / base_run_id
        
        # Check which run_id is canonical for our inputs_hash
        canonical_run_id = None
        
        # First check base run_id
        if base_dir.exists():
            base_manifest_path = base_dir / "manifest.json"
            if base_manifest_path.exists():
                with base_manifest_path.open("r") as f:
                    base_manifest = json.load(f)
                if base_manifest.get("inputs_hash") == inputs_hash1:
                    canonical_run_id = base_run_id
        
        # If base doesn't match, scan for suffixed versions
        if canonical_run_id is None:
            suffix = 2
            while True:
                suffixed_run_id = f"{base_run_id}-{suffix}"
                suffixed_dir = runs_dir / suffixed_run_id
                if not suffixed_dir.exists():
                    break
                suffixed_manifest_path = suffixed_dir / "manifest.json"
                if suffixed_manifest_path.exists():
                    with suffixed_manifest_path.open("r") as f:
                        suffixed_manifest = json.load(f)
                    if suffixed_manifest.get("inputs_hash") == inputs_hash1:
                        canonical_run_id = suffixed_run_id
                        break
                suffix += 1
                if suffix > 1000:
                    break
        
        if canonical_run_id is None:
            print(f"✗ Could not find canonical run_id for inputs_hash {inputs_hash1[:40]}...")
            return False
        
        # Verify exactly one directory with this run_id exists
        canonical_dir = runs_dir / canonical_run_id
        if not canonical_dir.exists():
            print(f"✗ Canonical run directory does not exist: {canonical_dir}")
            return False
        
        print(f"✓ Single canonical run directory: {canonical_run_id}")
        print(f"  Path: {canonical_dir}")

        # Test 9: Deterministic collision suffix behavior
        print("\n[Test 9] Validate deterministic collision suffix")
        # Ensure deterministic baseline: remove any pre-existing suffixed siblings for this base
        suffix = 2
        removed_siblings = []
        while True:
            sibling_id = f"{run_id1}-{suffix}"
            sibling_dir = runs_dir / sibling_id
            if not sibling_dir.exists():
                break
            shutil.rmtree(sibling_dir)
            removed_siblings.append(sibling_id)
            suffix += 1
        if removed_siblings:
            print(f"  Removed pre-existing siblings: {', '.join(removed_siblings)}")

        base_manifest_path = runs_dir / run_id1 / "manifest.json"
        original_manifest_bytes = base_manifest_path.read_bytes()
        base_manifest_data = json.loads(original_manifest_bytes.decode("utf-8"))
        base_manifest_data["inputs_hash"] = "sha256:" + "f" * 64
        base_manifest_path.write_text(
            json.dumps(base_manifest_data, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        result3 = execute_instagram_copy_pipeline(repo_root, job_ref, params={})
        run_id3 = result3["run_id"]
        cleanup_ids.append(run_id3)

        expected_run_id3 = f"{run_id1}-2"
        if run_id3 != expected_run_id3:
            print(f"✗ Deterministic suffix mismatch: expected {expected_run_id3}, got {run_id3}")
            return False
        expected_artifact_dir = Path(repo_root) / "artifacts" / cleanup_job_id / run_id3
        if Path(result3["artifact_dir"]).resolve() != expected_artifact_dir.resolve():
            print("✗ Collision suffix artifact_dir mismatch")
            print(f"  Expected: {expected_artifact_dir}")
            print(f"  Actual:   {result3['artifact_dir']}")
            return False
        print(f"✓ Deterministic collision suffix used exactly: {run_id3}")

        # Restore base manifest before cleanup to keep state consistent
        base_manifest_path.write_bytes(original_manifest_bytes)

        # Test 10: Legacy consumer compatibility (symlink OR canonical discovery)
        print("\n[Test 10] Validate legacy consumer compatibility")
        legacy_alias = Path(repo_root) / "artifacts" / "runs" / run_id1
        canonical_manifest = Path(repo_root) / "artifacts" / cleanup_job_id / run_id1 / "manifest.json"
        if legacy_alias.exists():
            print(f"✓ Legacy alias exists: {legacy_alias}")
        elif canonical_manifest.exists():
            print("✓ Legacy alias absent but canonical manifest exists (reindex can discover canonical layout)")
        else:
            print("✗ Neither legacy alias nor canonical manifest exists")
            return False

        # Test 11: Manifest deterministic bytes across two clean runs
        print("\n[Test 11] Validate manifest byte identity across clean runs")
        excluded_fields = [
            "started_at",
            "finished_at",
            "queue_job_id",
            "langfuse_trace_id",
            "doctrine.resolved_at",
        ]
        print(f"  Excluded volatile fields: {', '.join(excluded_fields)}")
        print("  No other fields are ignored")

        baseline_manifest_bytes = normalized_manifest_bytes(manifest1)
        cleanup_test_artifacts(repo_root, [run_id1, run_id3], cleanup_job_id)

        clean_result = execute_instagram_copy_pipeline(repo_root, job_ref, params={})
        clean_run_id = clean_result["run_id"]
        cleanup_ids.append(clean_run_id)

        clean_manifest_path = Path(clean_result["artifact_dir"]) / "manifest.json"
        clean_manifest_data = json.loads(clean_manifest_path.read_text(encoding="utf-8"))
        clean_manifest_bytes = normalized_manifest_bytes(clean_manifest_data)
        if clean_manifest_bytes != baseline_manifest_bytes:
            print("✗ Normalized manifest bytes differ across clean runs with identical inputs")
            baseline_text = baseline_manifest_bytes.decode("utf-8")
            clean_text = clean_manifest_bytes.decode("utf-8")
            diff = list(
                difflib.unified_diff(
                    baseline_text.splitlines(),
                    clean_text.splitlines(),
                    fromfile="baseline_normalized_manifest.json",
                    tofile="clean_normalized_manifest.json",
                    lineterm="",
                )
            )
            if diff:
                print("  Diff (first 30 lines):")
                for line in diff[:30]:
                    print(f"    {line}")
            return False
        print(f"✓ Normalized manifest bytes identical across clean runs: run_id={clean_run_id}")

        # Test 12: Failure path leaves no tmp-* leftovers and no partial final dirs
        print("\n[Test 12] Validate atomic failure behavior")
        # Remove existing run so failure path cannot short-circuit via idempotent replay
        cleanup_test_artifacts(repo_root, [clean_run_id], cleanup_job_id)

        original_generate_text = pipeline_module.generate_text

        def _raise_generation_failure(*_args, **_kwargs):
            raise RuntimeError("forced smoke failure")

        pipeline_module.generate_text = _raise_generation_failure
        failed_run_id = None
        failed_artifact_dir = None
        try:
            execute_instagram_copy_pipeline(repo_root, job_ref, params={})
            print("✗ Expected forced generation failure, but pipeline succeeded")
            return False
        except Exception:
            # Discover most recent failed run manifest for this job_id
            job_runs_dir = Path(repo_root) / "artifacts" / cleanup_job_id
            candidates = sorted(
                [p for p in job_runs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for candidate in candidates:
                manifest_path = candidate / "manifest.json"
                if not manifest_path.exists():
                    continue
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if data.get("status") == "failed" and "forced smoke failure" in (data.get("error") or ""):
                    failed_run_id = data.get("run_id")
                    failed_artifact_dir = candidate
                    break

            if failed_run_id is None or failed_artifact_dir is None:
                print("✗ Could not locate failed run manifest for forced failure")
                return False

            cleanup_ids.append(failed_run_id)
            # Failed run must still be atomically finalized with manifest
            if not (failed_artifact_dir / "manifest.json").exists():
                print("✗ Failed run missing manifest.json")
                return False
            print(f"✓ Failed run finalized atomically: {failed_run_id}")
        finally:
            pipeline_module.generate_text = original_generate_text

        if not validate_no_temp_dirs(repo_root, cleanup_job_id):
            print("✗ tmp-* leftovers after failure path")
            return False
        print("✓ No tmp-* leftovers after failure path")
        
        
        print("\n" + "=" * 60)
        print("✓ ALL DETERMINISM SMOKE TESTS PASSED")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n✗ Smoke test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup test artifacts
        print(f"\n[Cleanup] Removing test run directories: {cleanup_ids}")
        cleanup_test_artifacts(repo_root, cleanup_ids, cleanup_job_id)


if __name__ == "__main__":
    success = run_smoke_tests()
    sys.exit(0 if success else 1)
