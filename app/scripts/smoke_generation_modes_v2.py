#!/usr/bin/env python3
"""Stage 5 Generation Modes Smoke Tests (Direct Pipeline Testing)

Tests generation modes by temporarily patching path resolution to use test briefs in artifacts/.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# Direct imports for testing
import yaml
from sigilzero.core.hashing import sha256_bytes
from sigilzero.pipelines import phase0_instagram_copy


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
    if len(parts) > 1 and parts[1].startswith("mode-test-"):
        test_path = repo_root_path / "artifacts" / ".test-jobs" / parts[1] / "/".join(parts[2:])
        return test_path
    
    p = (repo_root_path / rel_path).resolve()

    try:
        p.relative_to(repo_root_path)
    except ValueError:
        raise ValueError("job_ref resolves outside repository root")

    return p


def test_mode_a_single():
    """Mode A: Single output (backward compatibility)"""
    test_name = "test_mode_a_single"
    repo_root = "/app"
    job_id = "mode-test-001"
    
    try:
        # Create test brief file in artifacts/.test-jobs
        brief_dict = load_base_brief_spec()
        brief_dict["job_id"] = job_id
        brief_dict["generation_mode"] = "single"
        
        test_job_dir = Path(repo_root) / "artifacts" / ".test-jobs" / job_id
        test_job_dir.mkdir(parents=True, exist_ok=True)
        test_brief_path = test_job_dir / "brief.yaml"
        with open(test_brief_path, "w") as f:
            yaml.dump(brief_dict, f)
        
        job_ref = f"jobs/{job_id}/brief.yaml"
        
        # Execute twice with patched resolver
        with patch.object(phase0_instagram_copy, '_resolve_repo_path', patched_resolve_repo_path):
            results = []
            for i in range(2):
                result = phase0_instagram_copy.execute_instagram_copy_pipeline(
                    repo_root=repo_root,
                    job_ref=job_ref,
                )
                results.append(result)
        
        # Cleanup test brief
        shutil.rmtree(test_job_dir)
        
        # Verify
        run_id_1 = results[0]["run_id"]
        run_id_2 = results[1]["run_id"]
        
        if run_id_1 != run_id_2:
            print(f"FAIL {test_name}: run_ids differ ({run_id_1} vs {run_id_2})")
            cleanup_test_artifacts(repo_root, [run_id_1, run_id_2], job_id)
            return False
        
        # Check manifest
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id_1 / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        if "outputs/instagram_captions.md" not in manifest.get("artifacts", {}):
            print(f"FAIL {test_name}: missing outputs/instagram_captions.md")
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


def test_mode_b_variants():
    """Mode B: Variants with deterministic seeding"""
    test_name = "test_mode_b_variants"
    repo_root = "/app"
    job_id = "mode-test-002"
    
    try:
        brief_dict = load_base_brief_spec()
        brief_dict["job_id"] = job_id
        brief_dict["generation_mode"] = "variants"
        brief_dict["caption_variants"] = 3
        
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
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Check generation_metadata
        gen_meta = manifest.get("generation_metadata", {})
        if gen_meta.get("generation_mode") != "variants":
            print(f"FAIL {test_name}: wrong generation_mode")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        if gen_meta.get("variant_count") != 3:
            print(f"FAIL {test_name}: wrong variant_count")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Check seeds recorded
        seeds = gen_meta.get("seeds", {})
        if len(seeds) != 3:
            print(f"FAIL {test_name}: expected 3 seeds, got {len(seeds)}")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Check variant files
        artifacts = manifest.get("artifacts", {})
        expected = [
            "outputs/instagram_captions.md",
            "outputs/variants/01.md",
            "outputs/variants/02.md",
            "outputs/variants/03.md",
            "outputs/variants/variants.json",
        ]
        
        for exp_file in expected:
            if exp_file not in artifacts:
                print(f"FAIL {test_name}: missing {exp_file}")
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


def test_mode_c_format():
    """Mode C: Output format flexibility"""
    test_name = "test_mode_c_format"
    repo_root = "/app"
    job_id = "mode-test-003"
    
    try:
        brief_dict = load_base_brief_spec()
        brief_dict["job_id"] = job_id
        brief_dict["generation_mode"] = "format"
        brief_dict["output_formats"] = ["md", "json", "yaml"]
        
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
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Check all formats present
        artifacts = manifest.get("artifacts", {})
        expected = [
            "outputs/instagram_captions.md",
            "outputs/instagram_captions.json",
            "outputs/instagram_captions.yaml",
        ]
        
        for exp_file in expected:
            if exp_file not in artifacts:
                print(f"FAIL {test_name}: missing {exp_file}")
                cleanup_test_artifacts(repo_root, [run_id], job_id)
                return False
        
        # Verify JSON is valid
        json_path = Path(repo_root) / "artifacts" / job_id / run_id / "outputs" / "instagram_captions.json"
        json_data = json.loads(json_path.read_text())
        if not isinstance(json_data.get("captions"), list):
            print(f"FAIL {test_name}: JSON captions not a list")
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


def test_backward_compatibility():
    """Verify default mode maintains backward compatibility"""
    test_name = "test_backward_compatibility"
    repo_root = "/app"
    job_id = "mode-test-backcompat"
    
    try:
        brief_dict = load_base_brief_spec()
        brief_dict["job_id"] = job_id
        # No generation_mode specified - should default to "single"
        
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
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Should default to single
        gen_meta = manifest.get("generation_metadata", {})
        if gen_meta.get("generation_mode") != "single":
            print(f"FAIL {test_name}: default mode should be single")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Should have MD only
        artifacts = manifest.get("artifacts", {})
        if "outputs/instagram_captions.md" not in artifacts:
            print(f"FAIL {test_name}: missing outputs/instagram_captions.md")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Should NOT have variants
        if any("variants/" in key for key in artifacts.keys()):
            print(f"FAIL {test_name}: should not have variant files in default mode")
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


def test_mode_c_format_no_variants():
    """Mode C: Format mode should not generate multiple variants even if caption_variants > 1"""
    test_name = "test_mode_c_format_no_variants"
    repo_root = "/app"
    job_id = "mode-test-format-no-variants"
    
    try:
        brief_dict = load_base_brief_spec()
        brief_dict["job_id"] = job_id
        brief_dict["generation_mode"] = "format"
        brief_dict["caption_variants"] = 3  # Set to 3 but should be ignored in format mode
        brief_dict["output_formats"] = ["md", "json", "yaml"]
        
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
        manifest_path = Path(repo_root) / "artifacts" / job_id / run_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        
        # Check generation_metadata
        gen_meta = manifest.get("generation_metadata", {})
        if gen_meta.get("generation_mode") != "format":
            print(f"FAIL {test_name}: wrong generation_mode")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # CRITICAL: variant_count must be 1, not 3
        if gen_meta.get("variant_count") != 1:
            print(f"FAIL {test_name}: variant_count should be 1, got {gen_meta.get('variant_count')}")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Should NOT have seed_strategy (format mode doesn't use seeds)
        if "seed_strategy" in gen_meta:
            print(f"FAIL {test_name}: format mode should not have seed_strategy")
            cleanup_test_artifacts(repo_root, [run_id], job_id)
            return False
        
        # Check artifacts - should have all formats
        artifacts = manifest.get("artifacts", {})
        expected = [
            "outputs/instagram_captions.md",
            "outputs/instagram_captions.json",
            "outputs/instagram_captions.yaml",
        ]
        
        for exp_file in expected:
            if exp_file not in artifacts:
                print(f"FAIL {test_name}: missing {exp_file}")
                cleanup_test_artifacts(repo_root, [run_id], job_id)
                return False
        
        # Should NOT have variants/ directory
        for artifact_key in artifacts.keys():
            if "variants/" in artifact_key:
                print(f"FAIL {test_name}: format mode should not create variants/ files")
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


def main() -> int:
    print("=" * 60)
    print("Stage 5: Generation Modes Smoke Tests")
    print("=" * 60)
    
    tests = [
        test_mode_a_single,
        test_mode_b_variants,
        test_mode_c_format,
        test_mode_c_format_no_variants,
        test_backward_compatibility,
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
