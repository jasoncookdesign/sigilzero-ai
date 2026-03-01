#!/usr/bin/env python3
"""
Stage 12 Smoke Test: Release Candidate Hardening

Validates Phase 1.0 architectural invariants:
1. Canonical input snapshots exist and are canonical JSON.
2. inputs_hash is computed from snapshot hashes only.
3. run_id is derived deterministically from inputs_hash.
4. job_id comes from brief governance identifier.
5. Doctrine version + hash recorded and consistent with snapshot content.
6. Registry-based job_type routing covers all in-repo briefs.
7. Deterministic manifest serialization excludes nondeterministic fields.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.core.hashing import compute_inputs_hash, derive_run_id, sha256_bytes
from sigilzero.core.schemas import BriefSpec, RunManifest
from sigilzero.jobs import JOB_PIPELINE_REGISTRY, resolve_pipeline
from sigilzero.pipelines.phase0_instagram_copy import execute_instagram_copy_pipeline


CANONICAL_INPUT_SNAPSHOTS = [
    "inputs/brief.resolved.json",
    "inputs/context.resolved.json",
    "inputs/model_config.json",
    "inputs/doctrine.resolved.json",
]


def _canonical_json_bytes(path: Path) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8"))
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _assert_canonical_snapshot(path: Path) -> None:
    assert path.exists(), f"missing snapshot: {path}"
    actual = path.read_bytes()
    expected = _canonical_json_bytes(path)
    assert actual == expected, f"snapshot is not canonical JSON: {path}"


def _assert_registry_coverage(repo_root: Path) -> None:
    briefs = sorted((repo_root / "jobs").glob("**/brief.yaml"))
    assert briefs, "no brief.yaml files found under jobs/"

    missing = []
    for brief_path in briefs:
        with brief_path.open("r", encoding="utf-8") as f:
            brief_data = yaml.safe_load(f) or {}
        if not isinstance(brief_data, dict):
            missing.append((brief_path.as_posix(), "<invalid-brief>"))
            continue

        job_type = brief_data.get("job_type", "instagram_copy")
        if job_type not in JOB_PIPELINE_REGISTRY:
            missing.append((brief_path.as_posix(), job_type))
        else:
            resolve_pipeline(job_type)

    assert not missing, f"registry missing job_types: {missing}"


def _normalized_manifest_json(manifest: RunManifest) -> str:
    return json.dumps(manifest.model_dump(), sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    env_repo_root = os.getenv("SIGILZERO_REPO_ROOT")
    repo_root = Path(env_repo_root) if env_repo_root else Path(__file__).resolve().parents[2]
    if not repo_root.exists():
        print(f"✗ repo root not found: {repo_root}")
        return 1

    print("=" * 72)
    print("STAGE 12 - RELEASE CANDIDATE HARDENING SMOKE TEST")
    print("=" * 72)
    print(f"repo_root={repo_root}")

    _assert_registry_coverage(repo_root)
    print("✓ Registry coverage: all brief job_types resolve via code-defined registry")

    job_ref = "jobs/ig-test-001/brief.yaml"
    result = execute_instagram_copy_pipeline(str(repo_root), job_ref, params={"queue_job_id": "stage12-queue-1"})
    run_id = result["run_id"]
    run_dir = Path(result["artifact_dir"])
    manifest_path = run_dir / "manifest.json"

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    manifest = RunManifest.model_validate(manifest_data)

    # Governance identifier must come from brief
    brief_path = repo_root / job_ref
    with brief_path.open("r", encoding="utf-8") as f:
        brief_data = yaml.safe_load(f) or {}
    brief = BriefSpec.model_validate(brief_data)
    assert manifest.job_id == brief.job_id, "job_id in manifest must come from brief governance identifier"
    print("✓ Governance: manifest.job_id matches brief.job_id")

    # Canonical snapshot enforcement + snapshot hash verification
    snapshot_hashes = {}
    for rel_path in CANONICAL_INPUT_SNAPSHOTS:
        path = run_dir / rel_path
        _assert_canonical_snapshot(path)

    for snapshot_name, snapshot_meta in manifest.input_snapshots.items():
        rel = snapshot_meta.path
        snapshot_path = run_dir / rel
        assert snapshot_path.exists(), f"manifest snapshot path missing: {rel}"
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot_sha = sha256_bytes(snapshot_bytes)
        assert snapshot_sha == snapshot_meta.sha256, f"snapshot sha mismatch for {snapshot_name}"
        assert len(snapshot_bytes) == snapshot_meta.bytes, f"snapshot bytes mismatch for {snapshot_name}"
        snapshot_hashes[snapshot_name] = snapshot_sha
    print("✓ Canonical snapshots exist and match manifest hashes/byte counts")

    # Determinism from snapshot hashes only
    recomputed_inputs_hash = compute_inputs_hash(snapshot_hashes)
    assert recomputed_inputs_hash == manifest.inputs_hash, "inputs_hash must derive only from snapshot hashes"

    base_run_id = derive_run_id(manifest.inputs_hash or "")
    if manifest.run_id != base_run_id:
        assert manifest.run_id.startswith(base_run_id + "-"), "run_id must be base hash or deterministic suffix"
        suffix = manifest.run_id[len(base_run_id) + 1 :]
        assert suffix.isdigit() and int(suffix) >= 2, "run_id suffix must be deterministic integer >= 2"
        expected = derive_run_id(manifest.inputs_hash or "", int(suffix))
        assert expected == manifest.run_id, "run_id suffix derivation mismatch"
    print("✓ Determinism: inputs_hash and run_id derivation verified")

    # Doctrine governance checks
    doctrine_snapshot_path = run_dir / "inputs" / "doctrine.resolved.json"
    doctrine_snapshot = json.loads(doctrine_snapshot_path.read_text(encoding="utf-8"))
    assert manifest.doctrine is not None, "manifest.doctrine missing"
    assert doctrine_snapshot.get("version") == manifest.doctrine.version, "doctrine version mismatch"
    assert doctrine_snapshot.get("doctrine_id") == manifest.doctrine.doctrine_id, "doctrine_id mismatch"
    doctrine_content_hash = sha256_bytes(doctrine_snapshot.get("content", "").encode("utf-8"))
    assert doctrine_content_hash == doctrine_snapshot.get("sha256"), "doctrine content hash mismatch in snapshot"
    assert doctrine_content_hash == manifest.doctrine.sha256, "doctrine hash mismatch between snapshot and manifest"
    print("✓ Doctrine: version/hash recorded and content hash verified")

    # Deterministic manifest serialization excludes nondeterministic fields
    manifest_variant = RunManifest.model_validate(
        {
            **manifest_data,
            "started_at": "2030-01-01T00:00:00Z",
            "finished_at": "2030-01-01T00:00:05Z",
            "langfuse_trace_id": "trace-stage12-variant",
        }
    )

    stable_a = _normalized_manifest_json(manifest)
    stable_b = _normalized_manifest_json(manifest_variant)
    assert stable_a == stable_b, "deterministic manifest serialization changed due to nondeterministic fields"
    assert "langfuse_trace_id" not in stable_a
    assert "started_at" not in stable_a
    assert "finished_at" not in stable_a
    print("✓ Deterministic manifest serialization excludes nondeterministic trace/timestamp fields")

    print("\n✅ Stage 12 hardening smoke passed")

    # Cleanup only this run's canonical + legacy alias if present
    try:
        shutil.rmtree(run_dir)
        legacy_alias = repo_root / "artifacts" / "runs" / run_id
        if legacy_alias.exists() or legacy_alias.is_symlink():
            legacy_alias.unlink()
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
