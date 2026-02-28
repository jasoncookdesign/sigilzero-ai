#!/usr/bin/env python3
"""Quick Stage 5 validation - outputs only essential results"""
import sys
sys.path.insert(0, "/app")

from pathlib import Path
from sigilzero.pipelines.phase0_instagram_copy import execute_instagram_copy_pipeline
import json

print("=== STAGE 5 VALIDATION ===\n")

# Test 1: Mode A (single) - backward compat
print("[1] Mode A (single) - backward compat")
result1 = execute_instagram_copy_pipeline(
    repo_root="/app",
    job_ref="jobs/ig-test-001/brief.yaml",
    brief_overrides={"job_id": "validate-mode-a", "generation_mode": "single"},
)
run_id1 = result1["run_id"]
manifest1_path = Path(f"/app/artifacts/validate-mode-a/{run_id1}/manifest.json")
manifest1 = json.loads(manifest1_path.read_text())

# Check MD exists
has_md = "outputs/instagram_captions.md" in manifest1["artifacts"]
# Check mode
mode = manifest1.get("generation_metadata", {}).get("generation_mode")
#Check no variants
has_variants = any("variants/" in k for k in manifest1["artifacts"].keys())

print(f"  run_id: {run_id1}")
print(f"  MD output: {'✓' if has_md else '✗'}")
print(f"  Mode recorded: {mode} {'✓' if mode == 'single' else '✗'}")
print(f"  No variants: {'✓' if not has_variants else '✗'}")

# Test 2: Mode B (variants) - deterministic seeds
print("\n[2] Mode B (variants) - deterministic seeds")
result2 = execute_instagram_copy_pipeline(
    repo_root="/app",
    job_ref="jobs/ig-test-001/brief.yaml",
    brief_overrides={"job_id": "validate-mode-b", "generation_mode": "variants", "caption_variants": 3},
)
run_id2 = result2["run_id"]
manifest2_path = Path(f"/app/artifacts/validate-mode-b/{run_id2}/manifest.json")
manifest2 = json.loads(manifest2_path.read_text())

has_md2 = "outputs/instagram_captions.md" in manifest2["artifacts"]
mode2 = manifest2.get("generation_metadata", {}).get("generation_mode")
seeds = manifest2.get("generation_metadata", {}).get("seeds", {})
variant_count = manifest2.get("generation_metadata", {}).get("variant_count")

print(f"  run_id: {run_id2}")
print(f"  MD output: {'✓' if has_md2 else '✗'}")
print(f"  Mode: {mode2} {'✓' if mode2 == 'variants' else '✗'}")
print(f"  Variant count: {variant_count} {'✓' if variant_count == 3 else '✗'}")
print(f"  Seed count: {len(seeds)} {'✓' if len(seeds) == 3 else '✗'}")
print(f"  Seeds recorded: {list(seeds.keys())[:2]}... (truncated)")

# Test 3: Mode C (format)
print("\n[3] Mode C (format) - multiple formats")
result3 = execute_instagram_copy_pipeline(
    repo_root="/app",
    job_ref="jobs/ig-test-001/brief.yaml",
    brief_overrides={"job_id": "validate-mode-c", "generation_mode": "format", "output_formats": ["md", "json", "yaml"]},
)
run_id3 = result3["run_id"]
manifest3_path = Path(f"/app/artifacts/validate-mode-c/{run_id3}/manifest.json")
manifest3 = json.loads(manifest3_path.read_text())

artifacts = manifest3["artifacts"]
has_md3 = "outputs/instagram_captions.md" in artifacts
has_json = "outputs/instagram_captions.json" in artifacts
has_yaml = "outputs/instagram_captions.yaml" in artifacts

print(f"  run_id: {run_id3}")
print(f"  MD: {'✓' if has_md3 else '✗'}")
print(f"  JSON: {'✓' if has_json else '✗'}")
print(f"  YAML: {'✓' if has_yaml else '✗'}")

# Cleanup
print("\n[Cleanup]")
import shutil
for job_id in ["validate-mode-a", "validate-mode-b", "validate-mode-c"]:
    job_dir = Path(f"/app/artifacts/{job_id}")
    if job_dir.exists():
        shutil.rmtree(job_dir)
        print(f"  Removed artifacts/{job_id}")

print("\n=== VALIDATION COMPLETE ===")
