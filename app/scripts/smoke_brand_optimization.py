#!/usr/bin/env python3
"""
Stage 8: Brand Optimization smoke tests

Tests:
1. test_chain_determinism: Same prior + inputs → Same run_id (byte-perfect manifests)
2. test_chain_prior_change: Different prior → Different run_id (no silent drift)
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Tuple

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.pipelines.phase0_brand_optimization import run_brand_optimization


def test_chain_determinism() -> bool:
    """
    Test: Chain determinism - identical prior + inputs produce identical run_id.
    If prior_artifact snapshot + hash is correctly included in inputs_hash,
    then running with SAME prior_run_id should produce SAME run_id (byte-perfect).
    
    Setup:
    - Assumes Stage 7 artifact exists: artifacts/brand-score-001/faa5aa5e64e7454d9d789a455e59a63f/
    - Creates two independent runs with optimization-001 brief and prior_run_id=faa5aa5e...
    
    Assertion:
    - run_id_1 == run_id_2
    - manifest_bytes_1 == manifest_bytes_2
    """
    print("\n" + "="*70)
    print("TEST: Chain Determinism (Same Prior + Inputs → Same Run_ID)")
    print("="*70)
    
    repo_root = Path("/app")
    artifacts_dir = repo_root / "artifacts"
    
    # Verify Stage 7 artifact exists
    stage7_artifact = artifacts_dir / "brand-score-001" / "faa5aa5e64e7454d9d789a455e59a63f"
    if not stage7_artifact.exists():
        print(f"❌ SKIP: Stage 7 artifact not found at {stage7_artifact}")
        print("   Run Stage 7 smoke tests first to generate artifacts")
        return True  # Not a failure, just skip
    
    print(f"✓ Found Stage 7 artifact: {stage7_artifact}")
    
    # Run 1: Chain to Stage 7
    job_ref_1 = "jobs/optimization-001/brief.yaml"
    print(f"\n[Run 1] Executing: job_ref={job_ref_1}")
    
    try:
        result_1 = run_brand_optimization(
            job_ref=job_ref_1,
            repo_root=str(repo_root),
        )
        run_id_1 = result_1.run_id
        artifact_dir_1 = artifacts_dir / "optimization-001" / run_id_1
        print(f"✓ Run 1 complete: run_id={run_id_1}")
    except Exception as e:
        print(f"❌ Run 1 failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Run 2: Chain to SAME Stage 7 artifact
    job_ref_2 = "jobs/optimization-001/brief.yaml"
    print(f"\n[Run 2] Executing: job_ref={job_ref_2}")
    
    try:
        result_2 = run_brand_optimization(
            job_ref=job_ref_2,
            repo_root=str(repo_root),
        )
        run_id_2 = result_2.run_id
        artifact_dir_2 = artifacts_dir / "optimization-001" / run_id_2
        print(f"✓ Run 2 complete: run_id={run_id_2}")
    except Exception as e:
        print(f"❌ Run 2 failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Assertion 1: run_ids match
    if run_id_1 != run_id_2:
        print(f"\n❌ FAIL: Run IDs differ (non-deterministic)")
        print(f"   Run 1: {run_id_1}")
        print(f"   Run 2: {run_id_2}")
        return False
    
    print(f"\n✓ PASS: Run IDs match (deterministic)")
    print(f"   Both runs: {run_id_1}")
    
    # Assertion 2: manifest bytes match (byte-perfect)
    manifest_path_1 = artifact_dir_1 / "manifest.json"
    manifest_path_2 = artifact_dir_2 / "manifest.json"
    
    if not manifest_path_1.exists() or not manifest_path_2.exists():
        print(f"❌ Manifest files not found")
        return False
    
    with open(manifest_path_1, "rb") as f:
        manifest_bytes_1 = f.read()
    with open(manifest_path_2, "rb") as f:
        manifest_bytes_2 = f.read()
    
    if manifest_bytes_1 != manifest_bytes_2:
        print(f"\n❌ FAIL: Manifest bytes differ (non-deterministic)")
        print(f"   Run 1 bytes: {len(manifest_bytes_1)}")
        print(f"   Run 2 bytes: {len(manifest_bytes_2)}")
        # Show diff
        m1 = json.loads(manifest_bytes_1)
        m2 = json.loads(manifest_bytes_2)
        if m1 != m2:
            for key in set(list(m1.keys()) + list(m2.keys())):
                if m1.get(key) != m2.get(key):
                    print(f"   Difference in '{key}':")
                    print(f"     Run 1: {m1.get(key)}")
                    print(f"     Run 2: {m2.get(key)}")
        return False
    
    print(f"✓ PASS: Manifest bytes match (byte-perfect)")
    print(f"   Both manifests: {len(manifest_bytes_1)} bytes")
    
    # Verify all 5 input snapshots present
    required_snapshots = [
        "brief.resolved.json",
        "context.resolved.json",
        "model_config.json",
        "doctrine.resolved.json",
        "prior_artifact.resolved.json",
    ]
    
    inputs_dir = artifact_dir_1 / "inputs"
    missing_snapshots = []
    for snapshot in required_snapshots:
        snapshot_path = inputs_dir / snapshot
        if not snapshot_path.exists():
            missing_snapshots.append(snapshot)
    
    if missing_snapshots:
        print(f"\n❌ FAIL: Missing input snapshots:")
        for snapshot in missing_snapshots:
            print(f"   - {snapshot}")
        return False
    
    print(f"✓ PASS: All 5 input snapshots present")
    for snapshot in required_snapshots:
        snapshot_path = inputs_dir / snapshot
        size = snapshot_path.stat().st_size
        print(f"   - {snapshot}: {size} bytes")
    
    # Verify chain_metadata in manifest
    manifest = json.loads(manifest_bytes_1)
    if "chain_metadata" not in manifest:
        print(f"\n❌ FAIL: chain_metadata missing from manifest")
        return False
    
    chain_meta = manifest["chain_metadata"]
    if not chain_meta.get("is_chainable_stage"):
        print(f"\n❌ FAIL: is_chainable_stage not set")
        return False
    
    if not chain_meta.get("prior_stages"):
        print(f"\n❌ FAIL: prior_stages list empty")
        return False
    
    prior_stage = chain_meta["prior_stages"][0]
    if prior_stage.get("stage") != "brand_compliance_score":
        print(f"\n❌ FAIL: prior_stage.stage mismatch")
        print(f"   Expected: 'brand_compliance_score'")
        print(f"   Got: '{prior_stage.get('stage')}'")
        print(f"   Full prior_stage: {prior_stage}")
        return False
    
    if prior_stage.get("run_id") != "faa5aa5e64e7454d9d789a455e59a63f":
        print(f"\n❌ FAIL: prior_stage.run_id mismatch")
        return False
    
    print(f"✓ PASS: Chain metadata correct")
    print(f"   is_chainable_stage: {chain_meta['is_chainable_stage']}")
    print(f"   prior_stage: {prior_stage['stage']} (run_id: {prior_stage['run_id'][:8]}...)")
    
    return True


def test_chain_prior_change_changes_run_id() -> bool:
    """
    Test: Chain prior change - different prior output content produces different run_id.
    This validates the "no silent drift" invariant (BLOCKER 5 FIX):
    If prior output files change, Stage 8 run_id MUST change.
    
    Strategy:
    - Run 1: Chain to real Stage 7 artifact (compliance_scores.json)
    - Run 2: Modify compliance_scores.json content
    - Run 3: Chain to modified artifact
    - Assert: run_id_3 != run_id_1 (proves drift is detected)
    
    Assertion:
    - run_id_real != run_id_modified_prior
    - (Proves prior output content participates in inputs_hash)
    """
    print("\n" + "="*70)
    print("TEST: Chain Prior Output Change (Different Prior Outputs → Different Run_ID)")
    print("="*70)
    
    repo_root = Path("/app")
    artifacts_dir = repo_root / "artifacts"
    
    # Verify Stage 7 artifact exists (real prior)
    stage7_artifact = artifacts_dir / "brand-score-001" / "faa5aa5e64e7454d9d789a455e59a63f"
    if not stage7_artifact.exists():
        print(f"⚠ SKIP: Stage 7 artifact not found")
        return True
    
    # Run 1: Chain to original Stage 7 artifact
    print(f"\n[Run 1] Chain to ORIGINAL Stage 7 artifact")
    job_ref_1 = "jobs/optimization-001/brief.yaml"
    
    try:
        result_1 = run_brand_optimization(job_ref_1, str(repo_root))
        run_id_1 = result_1.run_id
        print(f"✓ Run 1 complete: run_id={run_id_1}")
    except Exception as e:
        print(f"❌ Run 1 failed: {e}")
        return False
    
    # Run 2: Modify prior output file
    print(f"\n[Run 2] Modifying Stage 7 output file...")
    original_output = stage7_artifact / "outputs" / "compliance_scores.json"
    backup_output = original_output.with_suffix(".json.backup")
    
    try:
        # Backup original
        if original_output.exists():
            shutil.copy2(original_output, backup_output)
            
            # Modify content
            modified_content = {"modified": True, "original": False}
            with original_output.open("w") as f:
                json.dump(modified_content, f)
            print(f"✓ Modified compliance_scores.json")
    except Exception as e:
        print(f"❌ Modification failed: {e}")
        return False
    
    # Run 3: Chain to modified Stage 7 artifact
    print(f"\n[Run 3] Chain to MODIFIED Stage 7 artifact")
    job_ref_3 = "jobs/optimization-001/brief.yaml"
    
    try:
        result_3 = run_brand_optimization(job_ref_3, str(repo_root))
        run_id_3 = result_3.run_id
        print(f"✓ Run 3 complete: run_id={run_id_3}")
    except Exception as e:
        print(f"❌ Run 3 failed: {e}")
        # Restore before failing
        try:
            shutil.copy2(backup_output, original_output)
        except:
            pass
        return False
    finally:
        # Restore original content
        try:
            if backup_output.exists():
                shutil.copy2(backup_output, original_output)
                backup_output.unlink()
                print(f"✓ Restored original compliance_scores.json")
        except Exception as e:
            print(f"⚠ Warning: Could not restore original: {e}")
    
    # Assertion: run_ids should differ (prior output change → run_id change)
    if run_id_1 == run_id_3:
        print(f"\n❌ FAIL: Run IDs are identical (drift vulnerability!)")
        print(f"   Original prior: {run_id_1}")
        print(f"   Modified prior: {run_id_3}")
        print(f"   This means prior output changes are NOT detected!")
        return False
    
    print(f"\n✓ PASS: Run IDs differ (prior output change detected)")
    print(f"   Original prior: {run_id_1}")
    print(f"   Modified prior: {run_id_3}")
    print(f"   Proof: prior output file hashes participate in inputs_hash")
    
    return True


def main():
    """Run all Stage 8 smoke tests."""
    print("\n" + "█"*70)
    print("█  STAGE 8 SMOKE TESTS: Brand Optimization (Chainable Pipelines)")
    print("█"*70)
    
    results = {}
    
    # Test 1: Chain determinism
    results["chain_determinism"] = test_chain_determinism()
    
    # Test 2: Chain prior change
    results["chain_prior_change"] = test_chain_prior_change_changes_run_id()
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
