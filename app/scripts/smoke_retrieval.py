#!/usr/bin/env python3
"""Stage 6 Retrieval Smoke Tests

Validates query-aware corpus retrieval with determinism guarantees:
1. Same query → same run_id (deterministic retrieval)
2. Different query → different inputs_hash/run_id
3. Glob mode backward compatibility (unchanged behavior)

Retrieval config and selected_items are recorded in snapshot for audit.
Verify validates snapshot integrity, not live corpus changes.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from sigilzero.pipelines import phase0_instagram_copy
from sigilzero.core.hashing import sha256_bytes


def cleanup_test_artifacts(repo_root: str, run_ids: List[str], job_id: str) -> None:
    """Clean up test run directories."""
    artifacts_root = Path(repo_root) / "artifacts"
    for run_id in run_ids:
        canonical_run_dir = artifacts_root / job_id / run_id
        if canonical_run_dir.exists():
            shutil.rmtree(canonical_run_dir)
        
        legacy_run_dir = artifacts_root / "runs" / run_id
        if legacy_run_dir.is_symlink() or legacy_run_dir.is_file():
            legacy_run_dir.unlink()
        elif legacy_run_dir.exists():
            shutil.rmtree(legacy_run_dir)


def load_base_brief_spec() -> Dict[str, Any]:
    """Load the base ig-test-001 brief as a dict."""
    brief_path = Path("/app/jobs/ig-test-001/brief.yaml")
    return yaml.safe_load(brief_path.read_text())


def patched_resolve_repo_path(repo_root: str, rel_path: str) -> Path:
    """Patched _resolve_repo_path that allows test briefs from artifacts/.test-jobs"""
    if Path(rel_path).is_absolute():
        raise ValueError("job_ref must be relative")

    parts = Path(rel_path).parts
    if not parts or parts[0] != "jobs" or any(part == ".." for part in parts):
        raise ValueError("job_ref must resolve under jobs/")

    repo_root_path = Path(repo_root).resolve()
    
    # For test jobs, redirect to artifacts/.test-jobs
    if len(parts) > 1 and parts[1].startswith("retrieve-test-"):
        test_path = repo_root_path / "artifacts" / ".test-jobs" / parts[1] / "/".join(parts[2:])
        return test_path
    
    p = (repo_root_path / rel_path).resolve()

    try:
        p.relative_to(repo_root_path)
    except ValueError:
        raise ValueError("job_ref resolves outside repository root")

    return p


def test_retrieval_determinism():
    """Retrieval mode: same query should produce same run_id"""
    test_name = "test_retrieval_determinism"
    repo_root = "/app"
    job_id = "retrieve-test-001"
    
    try:
        brief_dict = load_base_brief_spec()
        brief_dict["job_id"] = job_id
        brief_dict["context_mode"] = "retrieve"
        brief_dict["context_query"] = "brand identity and positioning"
        brief_dict["retrieval_top_k"] = 5
        
        test_job_dir = Path(repo_root) / "artifacts" / ".test-jobs" / job_id
        test_job_dir.mkdir(parents=True, exist_ok=True)
        test_brief_path = test_job_dir / "brief.yaml"
        with open(test_brief_path, "w") as f:
            yaml.dump(brief_dict, f)
        
        job_ref = f"jobs/{job_id}/brief.yaml"
        
        # Execute twice with same query
        with patch.object(phase0_instagram_copy, '_resolve_repo_path', patched_resolve_repo_path):
            result1 = phase0_instagram_copy.execute_instagram_copy_pipeline(
                repo_root=repo_root,
                job_ref=job_ref,
            )
            result2 = phase0_instagram_copy.execute_instagram_copy_pipeline(
                repo_root=repo_root,
                job_ref=job_ref,
            )
        
        shutil.rmtree(test_job_dir)
        
        run_id_1 = result1["run_id"]
        run_id_2 = result2["run_id"]
        
        if run_id_1 != run_id_2:
            print(f"FAIL {test_name}: run_ids differ ({run_id_1} vs {run_id_2})")
            cleanup_test_artifacts(repo_root, [run_id_1, run_id_2], job_id)
            return False
        
        # Check manifest has retrieval metadata
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id_1 / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Check context snapshot has retrieval data
        context_snapshot_path = Path(repo_root) / "artifacts" / job_id / run_id_1 / "inputs" / "context.resolved.json"
        context_snapshot = json.loads(context_snapshot_path.read_text())
        context_spec = context_snapshot.get("spec", {})
        
        if context_spec.get("strategy") != "retrieve":
            print(f"FAIL {test_name}: context strategy should be 'retrieve', got {context_spec.get('strategy')}")
            cleanup_test_artifacts(repo_root, [run_id_1], job_id)
            return False
        
        if context_spec.get("query") != "brand identity and positioning":
            print(f"FAIL {test_name}: query mismatch")
            cleanup_test_artifacts(repo_root, [run_id_1], job_id)
            return False
        
        if not context_spec.get("retrieval_config"):
            print(f"FAIL {test_name}: missing retrieval_config")
            cleanup_test_artifacts(repo_root, [run_id_1], job_id)
            return False
        
        if not context_spec.get("selected_items"):
            print(f"FAIL {test_name}: missing selected_items")
            cleanup_test_artifacts(repo_root, [run_id_1], job_id)
            return False
        
        print(f"PASS {test_name}")
        cleanup_test_artifacts(repo_root, [run_id_1], job_id)
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_query_change_changes_run_id():
    """Different query should produce different run_id"""
    test_name = "test_query_change_changes_run_id"
    repo_root = "/app"
    job_id_1 = "retrieve-test-002a"
    job_id_2 = "retrieve-test-002b"
    
    try:
        # First query
        brief_dict_1 = load_base_brief_spec()
        brief_dict_1["job_id"] = job_id_1
        brief_dict_1["context_mode"] = "retrieve"
        brief_dict_1["context_query"] = "brand voice and tone"
        brief_dict_1["retrieval_top_k"] = 5
        
        test_job_dir_1 = Path(repo_root) / "artifacts" / ".test-jobs" / job_id_1
        test_job_dir_1.mkdir(parents=True, exist_ok=True)
        test_brief_path_1 = test_job_dir_1 / "brief.yaml"
        with open(test_brief_path_1, "w") as f:
            yaml.dump(brief_dict_1, f)
        
        # Second query (different)
        brief_dict_2 = load_base_brief_spec()
        brief_dict_2["job_id"] = job_id_2
        brief_dict_2["context_mode"] = "retrieve"
        brief_dict_2["context_query"] = "marketing strategy and tactics"
        brief_dict_2["retrieval_top_k"] = 5
        
        test_job_dir_2 = Path(repo_root) / "artifacts" / ".test-jobs" / job_id_2
        test_job_dir_2.mkdir(parents=True, exist_ok=True)
        test_brief_path_2 = test_job_dir_2 / "brief.yaml"
        with open(test_brief_path_2, "w") as f:
            yaml.dump(brief_dict_2, f)
        
        # Execute both
        with patch.object(phase0_instagram_copy, '_resolve_repo_path', patched_resolve_repo_path):
            result1 = phase0_instagram_copy.execute_instagram_copy_pipeline(
                repo_root=repo_root,
                job_ref=f"jobs/{job_id_1}/brief.yaml",
            )
            result2 = phase0_instagram_copy.execute_instagram_copy_pipeline(
                repo_root=repo_root,
                job_ref=f"jobs/{job_id_2}/brief.yaml",
            )
        
        shutil.rmtree(test_job_dir_1)
        shutil.rmtree(test_job_dir_2)
        
        run_id_1 = result1["run_id"]
        run_id_2 = result2["run_id"]
        
        if run_id_1 == run_id_2:
            print(f"FAIL {test_name}: different queries should produce different run_ids")
            cleanup_test_artifacts(repo_root, [run_id_1], job_id_1)
            cleanup_test_artifacts(repo_root, [run_id_2], job_id_2)
            return False
        
        print(f"PASS {test_name}")
        cleanup_test_artifacts(repo_root, [run_id_1], job_id_1)
        cleanup_test_artifacts(repo_root, [run_id_2], job_id_2)
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_glob_mode_unchanged():
    """Glob mode should still work as before (backward compatibility)"""
    test_name = "test_glob_mode_unchanged"
    repo_root = "/app"
    job_id = "retrieve-test-003"
    
    try:
        brief_dict = load_base_brief_spec()
        brief_dict["job_id"] = job_id
        brief_dict["context_mode"] = "glob"  # Explicit glob mode
        
        test_job_dir = Path(repo_root) / "artifacts" / ".test-jobs" / job_id
        test_job_dir.mkdir(parents=True, exist_ok=True)
        test_brief_path = test_job_dir / "brief.yaml"
        with open(test_brief_path, "w") as f:
            yaml.dump(brief_dict, f)
        
        job_ref = f"jobs/{job_id}/brief.yaml"
        
        with patch.object(phase0_instagram_copy, '_resolve_repo_path', patched_resolve_repo_path):
            result = phase0_instagram_copy.execute_instagram_copy_pipeline(
                repo_root=repo_root,
                job_ref=job_ref,
            )
        
        shutil.rmtree(test_job_dir)
        
        run_id = result["run_id"]
        
        # Check context snapshot uses glob strategy
        context_snapshot_path = Path(repo_root) / "artifacts" / job_id / run_id / "inputs" / "context.resolved.json"
        context_snapshot = json.loads(context_snapshot_path.read_text())
        context_spec = context_snapshot.get("spec", {})
        
        if context_spec.get("strategy") != "glob":
            print(f"FAIL {test_name}: context strategy should be 'glob', got {context_spec.get('strategy')}")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Should NOT have retrieval_config or selected_items
        if context_spec.get("retrieval_config") is not None:
            print(f"FAIL {test_name}: glob mode should not have retrieval_config")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        print(f"PASS {test_name}")
        cleanup_test_artifacts(repo_root, [run_id], job_id)
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_legacy_glob_run_id_idempotence():
    """
    Legacy glob briefs must produce stable (idempotent) run_id across runs.
    
    Governance Note:
    - This test proves idempotence, not pre-Stage backward compatibility.
    - To prove backward compatibility, we would need a golden run_id from
      a pre-Stage-5/6 baseline commit.
    - Current implementation excludes Stage 5/6 default fields to preserve 
      snapshot structure, but this is not validated against a pre-Stage baseline.
    """
    test_name = "test_legacy_glob_run_id_idempotence"
    repo_root = "/app"
    
    try:
        # Use the actual ig-test-001 brief which predates Stage 6
        job_ref = "jobs/ig-test-001/brief.yaml"
        
        # Run pipeline twice
        result1 = phase0_instagram_copy.execute_instagram_copy_pipeline(
            repo_root=repo_root,
            job_ref=job_ref,
        )
        
        result2 = phase0_instagram_copy.execute_instagram_copy_pipeline(
            repo_root=repo_root,
            job_ref=job_ref,
        )
        
        run_id_1 = result1["run_id"]
        run_id_2 = result2["run_id"]
        
        # Verify run_id is stable across runs (idempotence)
        if run_id_1 != run_id_2:
            print(f"FAIL {test_name}: run_id not stable")
            print(f"  First run:  {run_id_1}")
            print(f"  Second run: {run_id_2}")
            return False
        
        # Verify Stage 5/6 default fields are NOT in brief snapshot
        # (This maintains snapshot structure consistency)
        brief_snapshot_path = Path(repo_root) / "artifacts" / "ig-test-001" / run_id_1 / "inputs" / "brief.resolved.json"
        brief_snapshot = json.loads(brief_snapshot_path.read_text())
        
        # Stage 6 fields should be excluded when in default glob mode
        if "context_mode" in brief_snapshot:
            print(f"FAIL {test_name}: brief snapshot should not contain context_mode in glob mode")
            return False
        
        if "context_query" in brief_snapshot:
            print(f"FAIL {test_name}: brief snapshot should not contain context_query in glob mode")
            return False
        
        # Stage 5 fields should be excluded when at defaults
        if "generation_mode" in brief_snapshot:
            print(f"FAIL {test_name}: brief snapshot should not contain generation_mode when at default")
            return False
        
        print(f"PASS {test_name}: legacy run_id idempotence proven at {run_id_1}")
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main() -> int:
    print("=" * 60)
    print("Stage 6: Retrieval Smoke Tests")
    print("=" * 60)
    
    tests = [
        test_retrieval_determinism,
        test_query_change_changes_run_id,
        test_glob_mode_unchanged,
        test_legacy_glob_run_id_idempotence,
    ]
    
    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"ERROR {test_func.__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    passed = sum(results)
    total = len(results)
    
    print("=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
