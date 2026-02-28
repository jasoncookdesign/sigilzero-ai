#!/usr/bin/env python3
"""Stage 5 Generation Modes Smoke Tests

Validates generation modes while preserving determinism invariants:
1. Mode A (single): backward compatible, single output
2. Mode B (variants): deterministic N-variant generation with seeded randomness
3. Mode C (format): output format flexibility (md, json, yaml)
4. All modes must preserve snapshot-based inputs and deterministic run_id
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.pipelines.phase0_instagram_copy import execute_instagram_copy_pipeline
import sigilzero.pipelines.phase0_instagram_copy as pipeline_module
from sigilzero.core.hashing import sha256_bytes
import yaml


def cleanup_test_artifacts(repo_root: str, run_ids: List[str], job_id: str | None = None) -> None:
    """Clean up test run directories."""
    artifacts_root = Path(repo_root) / "artifacts"
    for run_id in run_ids:
        if job_id:
            canonical_run_dir = artifacts_root / job_id / run_id
            if canonical_run_dir.exists():
                shutil.rmtree(canonical_run_dir)
        
        legacy_run_dir = artifacts_root / "runs" / run_id
        if legacy_run_dir.is_symlink() or legacy_run_dir.is_file():
            legacy_run_dir.unlink()
        elif legacy_run_dir.exists():
            shutil.rmtree(legacy_run_dir)


def test_mode_a_single():
    """Mode A: Single output (backward compatibility)"""
    test_name = "test_mode_a_single"
    repo_root = "/app"
    job_id = "mode-test-001"
    
    try:
        # Load base brief
        brief_path = Path(repo_root) / "jobs" / "ig-test-001" / "brief.yaml"
        if not brief_path.exists():
            print(f"SKIP {test_name}: ig-test-001 brief not found")
            return True
        
        # Inject simple brief override (mode A is default)
        override_brief = {
            "job_id": job_id,
            "generation_mode": "single",
        }
        
        # Execute twice to test determinism
        results = []
        for i in range(2):
            result = execute_instagram_copy_pipeline(
                repo_root=repo_root,
                job_ref="jobs/ig-test-001/brief.yaml",
                brief_overrides=override_brief,
            )
            results.append(result)
        
        # Both runs should have same run_id (determinism)
        run_id_1 = results[0]["run_id"]
        run_id_2 = results[1]["run_id"]
        
        if run_id_1 != run_id_2:
            print(f"FAIL {test_name}: Mode A should be deterministic (run 1: {run_id_1} vs run 2: {run_id_2})")
            cleanup_test_artifacts(repo_root, [run_id_1, run_id_2], job_id)
            return False
        
        # Check that outputs/instagram_captions.md exists (backward compatibility)
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id_1 / "manifest.json"
        if not manifest_path.exists():
            print(f"FAIL {test_name}: Manifest not found at {manifest_path}")
            cleanup_test_artifacts(repo_root, [run_id_1], job_id)
            return False
        
        manifest = json.loads(manifest_path.read_text())
        if "outputs/instagram_captions.md" not in manifest.get("artifacts", {}):
            print(f"FAIL {test_name}: outputs/instagram_captions.md not in artifacts")
            cleanup_test_artifacts(repo_root, [run_id_1], job_id)
            return False
        
        print(f"PASS {test_name}")
        cleanup_test_artifacts(repo_root, [run_id_1], job_id)
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        return False


def test_mode_b_variants():
    """Mode B: Variants with deterministic seeding"""
    test_name = "test_mode_b_variants"
    repo_root = "/app"
    job_id = "mode-test-002"
    
    try:
        brief_path = Path(repo_root) / "jobs" / "ig-test-001" / "brief.yaml"
        if not brief_path.exists():
            print(f"SKIP {test_name}: ig-test-001 brief not found")
            return True
        
        override_brief = {
            "job_id": job_id,
            "generation_mode": "variants",
            "caption_variants": 3,
        }
        
        # Execute twice with same config
        results = []
        run_ids = []
        for i in range(2):
            result = execute_instagram_copy_pipeline(
                repo_root=repo_root,
                job_ref="jobs/ig-test-001/brief.yaml",
                brief_overrides=override_brief,
            )
            results.append(result)
            run_ids.append(result["run_id"])
        
        # Both should have same run_id (determinism from inputs_hash)
        if run_ids[0] != run_ids[1]:
            print(f"FAIL {test_name}: Variants should derive same run_id from inputs (run 1: {run_ids[0]} vs run 2: {run_ids[1]})")
            cleanup_test_artifacts(repo_root, run_ids, job_id)
            return False
        
        run_id = run_ids[0]
        
        # Check variant files and metadata
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Should have generation_metadata with seeds
        gen_meta = manifest.get("generation_metadata", {})
        if gen_meta.get("generation_mode") != "variants":
            print(f"FAIL {test_name}: generation_mode not set in metadata")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        if gen_meta.get("variant_count") != 3:
            print(f"FAIL {test_name}: Expected 3 variants, got {gen_meta.get('variant_count')}")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Should have seeds recorded
        seeds = gen_meta.get("seeds", {})
        if len(seeds) != 3:
            print(f"FAIL {test_name}: Expected 3 seeds, got {len(seeds)}")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Check variant files exist
        artifacts = manifest.get("artifacts", {})
        expected_files = [
            "outputs/instagram_captions.md",
            "outputs/variants/01.md",
            "outputs/variants/02.md",
            "outputs/variants/03.md",
            "outputs/variants/variants.json",
        ]
        
        for expected_file in expected_files:
            if expected_file not in artifacts:
                print(f"FAIL {test_name}: Missing {expected_file} in artifacts")
                cleanup_test_artifacts(repo_root, [run_id], job_id)
                return False
        
        # Verify variants.json is valid
        variants_json_path = Path(repo_root) / "artifacts" / job_id / run_id / "outputs" / "variants" / "variants.json"
        variants_json = json.loads(variants_json_path.read_text())
        if len(variants_json) != 3:
            print(f"FAIL {test_name}: variants.json should have 3 entries, got {len(variants_json)}")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        print(f"PASS {test_name}")
        cleanup_test_artifacts(repo_root, [run_id], job_id)
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        return False


def test_mode_c_format():
    """Mode C: Output format flexibility (md, json, yaml)"""
    test_name = "test_mode_c_format"
    repo_root = "/app"
    job_id = "mode-test-003"
    
    try:
        brief_path = Path(repo_root) / "jobs" / "ig-test-001" / "brief.yaml"
        if not brief_path.exists():
            print(f"SKIP {test_name}: ig-test-001 brief not found")
            return True
        
        override_brief = {
            "job_id": job_id,
            "generation_mode": "format",
            "output_formats": ["md", "json", "yaml"],
        }
        
        result = execute_instagram_copy_pipeline(
            repo_root=repo_root,
            job_ref="jobs/ig-test-001/brief.yaml",
            brief_overrides=override_brief,
        )
        
        run_id = result["run_id"]
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Check that all formats are present
        artifacts = manifest.get("artifacts", {})
        expected_files = [
            "outputs/instagram_captions.md",
            "outputs/instagram_captions.json",
            "outputs/instagram_captions.yaml",
        ]
        
        for expected_file in expected_files:
            if expected_file not in artifacts:
                print(f"FAIL {test_name}: Missing {expected_file} in artifacts")
                cleanup_test_artifacts(repo_root, [run_id], job_id)
                return False
        
        # Verify file contents are valid
        base_path = Path(repo_root) / "artifacts" / job_id / run_id / "outputs"
        
        # Verify JSON is valid
        json_path = base_path / "instagram_captions.json"
        json_data = json.loads(json_path.read_text())
        if not isinstance(json_data.get("captions"), list):
            print(f"FAIL {test_name}: JSON captions should be a list")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Verify YAML is valid
        yaml_path = base_path / "instagram_captions.yaml"
        yaml_data = yaml.safe_load(yaml_path.read_text())
        if not isinstance(yaml_data.get("captions"), list):
            print(f"FAIL {test_name}: YAML captions should be a list")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        print(f"PASS {test_name}")
        cleanup_test_artifacts(repo_root, [run_id], job_id)
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        return False


def test_backward_compatibility():
    """Verify Mode A (default) maintains backward compatibility with existing code"""
    test_name = "test_backward_compatibility"
    repo_root = "/app"
    job_id = "mode-test-backcompat"
    
    try:
        brief_path = Path(repo_root) / "jobs" / "ig-test-001" / "brief.yaml"
        if not brief_path.exists():
            print(f"SKIP {test_name}: ig-test-001 brief not found")
            return True
        
        # Execute with default brief (no generation_mode override = single)
        result = execute_instagram_copy_pipeline(
            repo_root=repo_root,
            job_ref="jobs/ig-test-001/brief.yaml",
            brief_overrides={"job_id": job_id},
        )
        
        run_id = result["run_id"]
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Default mode should be "single"
        gen_meta = manifest.get("generation_metadata", {})
        if gen_meta.get("generation_mode") != "single":
            print(f"FAIL {test_name}: Default generation_mode should be 'single'")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Should have exactly outputs/instagram_captions.md (no variants)
        artifacts = manifest.get("artifacts", {})
        if "outputs/instagram_captions.md" not in artifacts:
            print(f"FAIL {test_name}: Missing outputs/instagram_captions.md")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Should NOT have variant files
        if any("variants/" in key for key in artifacts.keys()):
            print(f"FAIL {test_name}: Default mode should not create variant files")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        print(f"PASS {test_name}")
        cleanup_test_artifacts(repo_root, [run_id], job_id)
        return True
    
    except Exception as e:
        print(f"FAIL {test_name}: {e}")
        return False


def main() -> int:
    """Run all generation mode smoke tests"""
    print("=" * 60)
    print("Stage 5: Generation Modes Smoke Tests")
    print("=" * 60)
    
    tests = [
        test_mode_a_single,
        test_mode_b_variants,
        test_mode_c_format,
        test_backward_compatibility,
    ]
    
    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"ERROR {test_func.__name__}: {e}")
            results.append(False)
    
    passed = sum(results)
    total = len(results)
    
    print("=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
