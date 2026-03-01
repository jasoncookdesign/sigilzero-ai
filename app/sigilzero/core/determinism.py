"""
Determinism Verification Module: Phase 1.0 Guardrails Enforcement

This module provides tools to verify determinism invariants:
1. Canonical Input Snapshots - All inputs must be written to disk
2. Deterministic run_id - Derived deterministically from inputs_hash
3. Governance job_id - From brief (not RQ UUID)
4. Doctrine as Hashed Input - Versioned and hashed
5. Filesystem Authoritative - Artifacts + manifest are truth
6. No Silent Drift - Input changes → inputs_hash change → run_id change
7. Backward Compatibility - API surface unchanged
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .hashing import sha256_bytes, compute_inputs_hash, derive_run_id
from .schemas import RunManifest


class SnapshotValidator:
    """Validates that all required snapshots are present and properly hashed.
    
    CRITICAL: This validator uses manifest.input_snapshots to determine required
    snapshots, NOT a hardcoded allowlist. This ensures it works for any pipeline,
    including those that add additional snapshots (Stage 7, 8, 9, etc).
    """
    
    @staticmethod
    def validate_run_directory(run_dir: Path) -> Tuple[bool, List[str]]:
        """Validate that all snapshots declared in manifest exist in directory.
        
        Args:
            run_dir: Path to run directory (e.g., artifacts/<job_id>/<run_id>)
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors: List[str] = []
        inputs_dir = run_dir / "inputs"
        
        if not inputs_dir.exists():
            errors.append(f"Inputs directory missing: {inputs_dir}")
            return False, errors
        
        # Check manifest exists
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            errors.append(f"Manifest missing: {manifest_path}")
            return False, errors
        
        # Load manifest to get declared snapshots
        try:
            with manifest_path.open("r") as f:
                manifest_data = json.load(f)
        except Exception as e:
            errors.append(f"Failed to load manifest: {e}")
            return False, errors
        
        # Check all snapshots declared in manifest.input_snapshots exist
        input_snapshots = manifest_data.get("input_snapshots", {})
        
        if not input_snapshots:
            errors.append("No input_snapshots declared in manifest")
            return False, errors
        
        for snapshot_name, snapshot_meta in input_snapshots.items():
            snapshot_path = run_dir / snapshot_meta.get("path")
            if not snapshot_path.exists():
                errors.append(f"Required snapshot missing: {snapshot_path.relative_to(run_dir)}")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_snapshot_hashes(run_dir: Path) -> Tuple[bool, List[str]]:
        """Validate that snapshot file hashes match manifest records.
        
        Args:
            run_dir: Path to run directory
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors: List[str] = []
        manifest_path = run_dir / "manifest.json"
        
        try:
            with manifest_path.open("r") as f:
                manifest_data = json.load(f)
        except Exception as e:
            errors.append(f"Failed to load manifest: {e}")
            return False, errors
        
        input_snapshots = manifest_data.get("input_snapshots", {})
        
        for snapshot_name, snapshot_meta in input_snapshots.items():
            snapshot_path = run_dir / snapshot_meta.get("path")
            if not snapshot_path.exists():
                errors.append(f"Snapshot file missing: {snapshot_path}")
                continue
            
            # Verify hash
            actual_hash = sha256_bytes(snapshot_path.read_bytes())
            expected_hash = snapshot_meta.get("sha256")
            
            if actual_hash != expected_hash:
                errors.append(
                    f"Snapshot hash mismatch {snapshot_name}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )
        
        return len(errors) == 0, errors


class DeterminismVerifier:
    """Verifies Phase 1.0 determinism invariants."""
    
    @staticmethod
    def verify_run_determinism(
        run_dir: Path,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Verify all determinism invariants for a run.
        
        Args:
            run_dir: Path to run directory
        
        Returns:
            Tuple of (is_valid, details_dict)
        """
        details: Dict[str, Any] = {
            "run_dir": str(run_dir),
            "checks": {},
        }
        
        # Check 1: Snapshots present
        snapshot_valid, snapshot_errors = SnapshotValidator.validate_run_directory(run_dir)
        details["checks"]["snapshots_present"] = {
            "valid": snapshot_valid,
            "errors": snapshot_errors,
        }
        
        # Check 2: Snapshot hashes
        hash_valid, hash_errors = SnapshotValidator.validate_snapshot_hashes(run_dir)
        details["checks"]["snapshot_hashes"] = {
            "valid": hash_valid,
            "errors": hash_errors,
        }
        
        # Check 3: inputs_hash derivation (manifest-declared snapshots, not hardcoded allowlist)
        manifest_path = run_dir / "manifest.json"
        try:
            with manifest_path.open("r") as f:
                manifest_data = json.load(f)
            
            # Reconstruct inputs_hash from EXACTLY the snapshots declared in manifest
            # Do NOT use a hardcoded allowlist - use what the manifest declares
            input_snapshots = manifest_data.get("input_snapshots", {})
            snapshot_hashes = {}
            
            # Collect all snapshot hashes from manifest (no filtering)
            for name, meta in input_snapshots.items():
                snapshot_sha256 = meta.get("sha256")
                if snapshot_sha256:
                    snapshot_hashes[name] = snapshot_sha256
            
            # Recompute inputs_hash from manifest-declared snapshots
            if snapshot_hashes:
                recomputed_inputs_hash = compute_inputs_hash(snapshot_hashes)
                recorded_inputs_hash = manifest_data.get("inputs_hash")
                
                inputs_hash_valid = recomputed_inputs_hash == recorded_inputs_hash
                details["checks"]["inputs_hash"] = {
                    "valid": inputs_hash_valid,
                    "recorded": recorded_inputs_hash,
                    "recomputed": recomputed_inputs_hash,
                    "snapshot_names": sorted(snapshot_hashes.keys()),
                }
            else:
                details["checks"]["inputs_hash"] = {
                    "valid": False,
                    "error": "No snapshot hashes found in manifest.input_snapshots",
                }
        except Exception as e:
            details["checks"]["inputs_hash"] = {
                "valid": False,
                "error": str(e),
            }
        
        # Check 4: run_id derivation
        try:
            with manifest_path.open("r") as f:
                manifest_data = json.load(f)
            
            inputs_hash = manifest_data.get("inputs_hash")
            recorded_run_id = manifest_data.get("run_id")
            
            if inputs_hash:
                recomputed_run_id = derive_run_id(inputs_hash)
                run_id_valid = recomputed_run_id == recorded_run_id
                details["checks"]["run_id"] = {
                    "valid": run_id_valid,
                    "recorded": recorded_run_id,
                    "recomputed": recomputed_run_id,
                }
            else:
                details["checks"]["run_id"] = {
                    "valid": False,
                    "error": "inputs_hash not found",
                }
        except Exception as e:
            details["checks"]["run_id"] = {
                "valid": False,
                "error": str(e),
            }
        
        # Check 5: job_id from brief
        try:
            brief_path = run_dir / "inputs" / "brief.resolved.json"
            if brief_path.exists():
                with brief_path.open("r") as f:
                    brief_data = json.load(f)
                brief_job_id = brief_data.get("job_id")
                recorded_job_id = manifest_data.get("job_id")
                
                job_id_valid = brief_job_id == recorded_job_id
                details["checks"]["job_id_governance"] = {
                    "valid": job_id_valid,
                    "brief_job_id": brief_job_id,
                    "manifest_job_id": recorded_job_id,
                }
            else:
                details["checks"]["job_id_governance"] = {
                    "valid": False,
                    "error": "Brief snapshot not found",
                }
        except Exception as e:
            details["checks"]["job_id_governance"] = {
                "valid": False,
                "error": str(e),
            }
        
        # Check 6: For chainable runs, validate prior_artifact snapshot structure
        try:
            is_chainable = manifest_data.get("chain_metadata", {}).get("is_chainable_stage", False)
            if is_chainable:
                chainable_valid = True
                chainable_errors = []
                
                # Must have prior_artifact snapshot
                prior_artifact_meta = input_snapshots.get("prior_artifact")
                if not prior_artifact_meta:
                    chainable_valid = False
                    chainable_errors.append("Chainable run missing prior_artifact in input_snapshots")
                else:
                    # Validate prior_artifact file structure
                    prior_artifact_path = run_dir / "inputs" / "prior_artifact.resolved.json"
                    if not prior_artifact_path.exists():
                        chainable_valid = False
                        chainable_errors.append("prior_artifact.resolved.json snapshot not found")
                    else:
                        try:
                            prior_artifact_data = json.loads(prior_artifact_path.read_text())
                            # Check required fields for drift detection
                            required_fields = ["prior_run_id", "prior_output_hashes", "required_outputs"]
                            for field in required_fields:
                                if field not in prior_artifact_data:
                                    chainable_valid = False
                                    chainable_errors.append(f"prior_artifact missing required field: {field}")
                        except Exception as e:
                            chainable_valid = False
                            chainable_errors.append(f"Failed to parse prior_artifact: {e}")
                
                details["checks"]["chainable_snapshot_structure"] = {
                    "valid": chainable_valid,
                    "errors": chainable_errors if chainable_errors else [],
                }
            else:
                # Non-chainable run should not have prior_artifact
                if "prior_artifact" in input_snapshots:
                    details["checks"]["chainable_snapshot_structure"] = {
                        "valid": False,
                        "error": "Non-chainable run has prior_artifact snapshot",
                    }
                else:
                    details["checks"]["chainable_snapshot_structure"] = {
                        "valid": True,
                        "error": None,
                    }
        except Exception as e:
            details["checks"]["chainable_snapshot_structure"] = {
                "valid": False,
                "error": str(e),
            }
        
        # Overall result
        all_valid = all(
            check.get("valid", False)
            for check in details["checks"].values()
        )
        
        return all_valid, details


def replay_run_idempotent(run_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    """Verify that a run can be replayed idempotently.
    
    Phase 1.0 Invariant: Same inputs → Same run_id → Idempotent replay
    
    Args:
        run_dir: Path to run directory
    
    Returns:
        Tuple of (can_replay, details_dict)
    """
    details: Dict[str, Any] = {
        "run_dir": str(run_dir),
        "can_replay": False,
        "errors": [],
    }
    
    # Verify manifest exists
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        details["errors"].append(f"Manifest not found: {manifest_path}")
        return False, details
    
    # Verify all snapshots exist and match
    snapshot_valid, snapshot_errors = SnapshotValidator.validate_run_directory(run_dir)
    if not snapshot_valid:
        details["errors"].extend(snapshot_errors)
        return False, details
    
    hash_valid, hash_errors = SnapshotValidator.validate_snapshot_hashes(run_dir)
    if not hash_valid:
        details["errors"].extend(hash_errors)
        return False, details
    
    # Can replay
    details["can_replay"] = True
    return True, details
