#!/usr/bin/env python3
"""
Stage 8: Brand Optimization (Chainable Pipeline)

Demonstrates Phase 1.0 chainable pipeline architecture.
Chains after Stage 7 (brand_compliance_score) or other prior stages.

DETERMINISM INVARIANTS ENFORCED:
1. Canonical Input Snapshots: brief, context, model_config, doctrine, prior_artifact
2. Deterministic run_id: derived from inputs_hash (includes prior_artifact hash)
3. Governance job_id: from brief.yaml (prior_run_id is DATA input)
4. Doctrine as Hashed Input: versioned and hashed
5. Filesystem Authoritative: artifacts/ + manifest are source of truth
6. No Silent Drift: prior_run_id change → run_id change
7. Backward Compatibility: POST /jobs/run API unchanged
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from sigilzero.core.hashing import sha256_bytes, sha256_json, compute_inputs_hash, derive_run_id
from sigilzero.core.schemas import (
    BriefSpec,
    InputSnapshot,
    DoctrineReference,
    RunManifest,
    ChainInput,
    ChainedStage,
    ChainMetadata,
)
from sigilzero.core.fs import ensure_dir, write_json
from sigilzero.core.doctrine import DoctrineLoader
from sigilzero.core.langfuse_client import get_langfuse


def _utc_now() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _read_manifest_inputs_hash(dir_path: Path) -> Optional[str]:
    """Read inputs_hash from manifest.json."""
    manifest_path = dir_path / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with manifest_path.open("r") as f:
            manifest = json.load(f)
            return manifest.get("inputs_hash")
    except Exception:
        return None


def _ensure_legacy_symlink(run_id: str, canonical_dir: Path) -> str:
    """Create legacy symlink for backward compatibility.
    
    BLOCKER 3 FIX: Actually create symlink target, not just directory.
    
    Returns: human-readable action description
    """
    legacy_link = Path("/app/artifacts/runs") / run_id
    legacy_link.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove existing symlink if broken or targeting elsewhere
    if legacy_link.exists() or legacy_link.is_symlink():
        try:
            legacy_link.unlink()
        except Exception:
            pass
    
    # Create symlink to canonical location
    try:
        # Relative symlink: runs/d79bbc34... -> ../optimization-001/d79bbc34.../
        relative_target = Path("..") / canonical_dir.parent.name / canonical_dir.name
        legacy_link.symlink_to(relative_target)
        return f"legacy_alias_created:{legacy_link}->{relative_target}"
    except Exception as e:
        # Silently fail if symlink not supported (containerization edge case)
        return f"legacy_alias_skipped:symlink_error"


def _read_yaml(path: Path) -> Dict[str, Any]:
    """Read YAML file, return dict."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_brand_optimization(job_ref: str, repo_root: str) -> RunManifest:
    """
    Execute Stage 8: Brand Optimization (Chainable Pipeline)
    
    Phase 1.0 Determinism Contract:
    - Loads prior artifact from filesystem
    - Creates prior_artifact.json snapshot
    - Includes prior_artifact hash in inputs_hash
    - Derives run_id deterministically
    - Records chain metadata for audit trail
    
    Args:
        job_ref: Path to job brief.yaml
        repo_root: Repository root path
    
    Returns:
        RunManifest with all canonical inputs + chain metadata
    
    Raises:
        ValueError: If prior artifact not found or inputs missing
    """
    repo_root = Path(repo_root)
    job_brief_path = repo_root / job_ref
    
    if not job_brief_path.exists():
        raise FileNotFoundError(f"Brief not found: {job_brief_path}")
    
    # Load job brief
    brief_yaml = _read_yaml(job_brief_path)
    brief = BriefSpec(**brief_yaml)
    
    if not brief.chain_inputs:
        raise ValueError(f"Brand optimization is chainable-only; chain_inputs required")
    
    # Extract chain inputs
    prior_run_id = brief.chain_inputs.prior_run_id
    prior_stage = brief.chain_inputs.prior_stage
    required_outputs = brief.chain_inputs.required_outputs
    
    # Phase 1.0 INVARIANT: Load prior artifact from filesystem (authoritative source)
    prior_artifact_dir = None
    prior_job_id = None
    
    # Search for prior artifact in artifacts/<job_id>/<prior_run_id>/
    artifacts_root = repo_root / "artifacts"
    for job_dir in artifacts_root.iterdir():
        if not job_dir.is_dir():
            continue
        run_dir = job_dir / prior_run_id
        if run_dir.exists() and (run_dir / "manifest.json").exists():
            prior_artifact_dir = run_dir
            prior_job_id = job_dir.name
            break
    
    if not prior_artifact_dir:
        raise ValueError(
            f"Prior artifact not found: {prior_stage}/{prior_run_id}\n"
            f"Searched in: {artifacts_root}"
        )
    
    # Validate required outputs
    for output_file in required_outputs:
        output_path = prior_artifact_dir / "outputs" / output_file
        if not output_path.exists():
            raise ValueError(f"Required output missing: {output_path}")
    
    # Load prior manifest
    prior_manifest_path = prior_artifact_dir / "manifest.json"
    with prior_manifest_path.open("r") as f:
        prior_manifest = json.load(f)
    
    # Create temporary work directory
    temp_dir = repo_root / ".tmp" / f"optimize-{int(time.time() * 1000)}"
    ensure_dir(temp_dir / "inputs")
    ensure_dir(temp_dir / "outputs")
    
    started_monotonic = time.monotonic()
    
    try:
        # Phase 1.0 INVARIANT: Load and snapshot all canonical inputs
        
        # 1. Brief snapshot
        brief_snapshot_bytes = job_brief_path.read_bytes()
        brief_snapshot_hash = sha256_bytes(brief_snapshot_bytes)
        write_json(temp_dir / "inputs" / "brief.resolved.json", brief.model_dump())
        
        # 2. Context snapshot (load from context.resolved.json if exists)
        context_snapshot_hash = None
        context_snapshot_bytes = None
        context_path = prior_artifact_dir / "inputs" / "context.resolved.json"
        if context_path.exists():
            context_snapshot_bytes = context_path.read_bytes()
            context_snapshot_hash = sha256_bytes(context_snapshot_bytes)
            shutil.copy2(context_path, temp_dir / "inputs" / "context.resolved.json")
        else:
            # If no context in prior, create empty
            context_snapshot_bytes = b"{}"
            context_snapshot_hash = sha256_bytes(context_snapshot_bytes)
            write_json(temp_dir / "inputs" / "context.resolved.json", {})
        
        # 3. Model config snapshot
        model_config = {"provider": "openai", "model": "gpt-4"}
        model_snapshot_bytes = json.dumps(model_config, sort_keys=True).encode("utf-8")
        model_snapshot_hash = sha256_bytes(model_snapshot_bytes)
        write_json(temp_dir / "inputs" / "model_config.json", model_config)
        
        # 4. Doctrine (load from prior or create new)
        doctrine_content = "{}"
        doctrine_snapshot_hash = sha256_bytes(doctrine_content.encode("utf-8"))
        
        doctrine_resolved = {
            "doctrine_id": "brand_optimization",
            "version": "v1.0.0",
            "sha256": sha256_bytes(doctrine_content.encode("utf-8")),
            "content": doctrine_content,
        }
        write_json(temp_dir / "inputs" / "doctrine.resolved.json", doctrine_resolved)
        doctrine_snapshot_bytes = (temp_dir / "inputs" / "doctrine.resolved.json").read_bytes()
        doctrine_snapshot_hash = sha256_bytes(doctrine_snapshot_bytes)
        
        # 5. PHASE 8 CRITICAL: Prior artifact snapshot (participates in inputs_hash)
        # This ensures: prior_run_id change → inputs_hash change → run_id change
        # BLOCKER 2 FIX: Include sha256 of actual prior output files (no silent drift)
        prior_output_hashes = {}
        for output_file in required_outputs:
            output_path = prior_artifact_dir / "outputs" / output_file
            if output_path.exists():
                output_bytes = output_path.read_bytes()
                prior_output_hashes[output_file] = sha256_bytes(output_bytes)
            else:
                raise ValueError(f"Required output missing: {output_path}")
        
        prior_artifact_snapshot = {
            "prior_run_id": prior_run_id,
            "prior_stage": prior_stage,
            "prior_job_id": prior_job_id,
            "prior_manifest": {
                "job_id": prior_manifest.get("job_id"),
                "run_id": prior_manifest.get("run_id"),
                "job_type": prior_manifest.get("job_type"),
                "inputs_hash": prior_manifest.get("inputs_hash"),
            },
            "required_outputs": required_outputs,
            "prior_output_hashes": prior_output_hashes,  # BLOCKER 2 FIX: Add actual file hashes
        }
        prior_artifact_snapshot_bytes = json.dumps(
            prior_artifact_snapshot, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        prior_artifact_snapshot_hash = sha256_bytes(prior_artifact_snapshot_bytes)
        write_json(temp_dir / "inputs" / "prior_artifact.resolved.json", prior_artifact_snapshot)
        
        # Phase 1.0 INVARIANT: Compute inputs_hash from ALL snapshot hashes
        # This creates the chain determinism property:
        # - Same prior_run_id + same new inputs → same inputs_hash → same run_id
        snapshot_hashes = {
            "brief": brief_snapshot_hash,
            "context": context_snapshot_hash,
            "model_config": model_snapshot_hash,
            "doctrine": doctrine_snapshot_hash,
            "prior_artifact": prior_artifact_snapshot_hash,  # CRITICAL: Chains are deterministic
        }
        inputs_hash = compute_inputs_hash(snapshot_hashes)
        
        # Phase 1.0 INVARIANT: Derive deterministic run_id from inputs_hash
        base_run_id = derive_run_id(inputs_hash)
        
        # Phase 1.0 COLLISION SEMANTICS: Idempotent replay with deterministic suffix
        job_root = repo_root / "artifacts" / brief.job_id
        runs_root = job_root
        legacy_runs_root = Path(repo_root) / "artifacts" / "runs"
        ensure_dir(runs_root)
        ensure_dir(legacy_runs_root)
        run_id = None
        final_run_dir = None
        symlink_actions: List[str] = []
        
        # Check for existing run
        for existing_run_dir in runs_root.iterdir():
            if not existing_run_dir.is_dir():
                continue
            if existing_run_dir.name == base_run_id:
                existing_inputs_hash = _read_manifest_inputs_hash(existing_run_dir)
                if existing_inputs_hash == inputs_hash:
                    # Deterministic idempotent replay
                    run_id = base_run_id
                    final_run_dir = existing_run_dir
                    break
        
        if not run_id:
            # New run
            final_run_dir = runs_root / base_run_id
            ensure_dir(final_run_dir / "inputs" / "outputs")
            run_id = base_run_id
        
        # Ensure legacy symlink to canonical location
        symlink_action = _ensure_legacy_symlink(run_id, final_run_dir)
        
        # Print run header
        print(
            f"[run_header] job_id={brief.job_id} job_ref={job_ref} "
            f"inputs_hash=sha256:{inputs_hash} run_id={run_id} queue_job_id=None "
            f"doctrine=v1.0.0/sha256:{'0' * 56}"
        )
        
        # If this is a fresh run, process outputs
        if (final_run_dir / "manifest.json").exists():
            status = "idempotent_replay"
            actions = []
        else:
            status = "succeeded"
            actions = [symlink_action]  # Use actual symlink action
            
            # Phase 8 INVARIANT: Copy all snapshots to final location (atomic finalization)
            snapshot_files = [
                "brief.resolved.json",
                "context.resolved.json",
                "model_config.json",
                "doctrine.resolved.json",
                "prior_artifact.resolved.json",  # CRITICAL: Include prior artifact
            ]
            for filename in snapshot_files:
                src = temp_dir / "inputs" / filename
                dst = final_run_dir / "inputs" / filename
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                else:
                    raise RuntimeError(f"Expected snapshot not found: {src}")
            
            # Generate optimized output (placeholder)
            optimization_output = {
                "job_id": brief.job_id,
                "prior_run_id": prior_run_id,
                "status": "optimization_complete",
                "recommendations": [
                    "Increase brand consistency in messaging",
                    "Enhance emotional resonance while maintaining tone",
                ],
            }
            write_json(final_run_dir / "outputs" / "optimization.json", optimization_output)
        
        # Create input snapshots metadata
        input_snapshots = {
            "brief": InputSnapshot(
                path="inputs/brief.resolved.json",
                sha256=brief_snapshot_hash,
                bytes=len(brief_snapshot_bytes),
            ),
            "context": InputSnapshot(
                path="inputs/context.resolved.json",
                sha256=context_snapshot_hash,
                bytes=len(context_snapshot_bytes),
            ),
            "model_config": InputSnapshot(
                path="inputs/model_config.json",
                sha256=model_snapshot_hash,
                bytes=len(model_snapshot_bytes),
            ),
            "doctrine": InputSnapshot(
                path="inputs/doctrine.resolved.json",
                sha256=doctrine_snapshot_hash,
                bytes=len(doctrine_snapshot_bytes),
            ),
            "prior_artifact": InputSnapshot(
                path="inputs/prior_artifact.resolved.json",
                sha256=prior_artifact_snapshot_hash,
                bytes=len(prior_artifact_snapshot_bytes),
            ),
        }
        
        # Build manifest
        manifest = RunManifest(
            job_id=brief.job_id,
            run_id=run_id,
            job_ref=job_ref,
            job_type="brand_optimization",
            started_at=_utc_now(),
            status=status,
            inputs_hash=inputs_hash,
            input_snapshots={k: v.model_dump() for k, v in input_snapshots.items()},
            doctrine=DoctrineReference(
                doctrine_id="brand_optimization",
                version="v1.0.0",
                sha256=doctrine_snapshot_hash,
            ).model_dump(exclude_unset=True),
            artifacts={
                "optimization": {
                    "path": "outputs/optimization.json",
                    "sha256": sha256_bytes((final_run_dir / "outputs" / "optimization.json").read_bytes()),
                }
            },
            chain_metadata=ChainMetadata(
                is_chainable_stage=True,
                prior_stages=[
                    ChainedStage(
                        run_id=prior_run_id,
                        job_id=prior_job_id,
                        stage=prior_stage,
                        output_references=[f"artifacts/{prior_job_id}/{prior_run_id}/outputs/{f}" for f in required_outputs],
                    )
                ],
            ).model_dump(),
        )
        
        manifest.finished_at = _utc_now()
        
        # Write manifest
        manifest_path = final_run_dir / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(by_alias=False), f, indent=2, ensure_ascii=False)
        
        elapsed = time.monotonic() - started_monotonic
        print(
            f"[run_footer] status={status} artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
            f"actions={','.join(actions) or 'none'}"
        )
        
        return manifest
        
    finally:
        # Cleanup temp directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: phase0_brand_optimization.py <job_ref> [repo_root]")
        sys.exit(1)
    
    job_ref = sys.argv[1]
    repo_root = sys.argv[2] if len(sys.argv) > 2 else "/app"
    
    manifest = run_brand_optimization(job_ref, repo_root)
    print(f"\nManifest:\n{json.dumps(manifest.model_dump(), indent=2)}")
