#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.core.db import connect, exec_sql, init_db
from sigilzero.core.hashing import compute_inputs_hash, derive_run_id, sha256_bytes


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _discover_run_dirs(repo_root: Path) -> List[Tuple[Path, str]]:
    artifacts_root = repo_root / "artifacts"
    if not artifacts_root.exists():
        return []

    run_dirs: List[Tuple[Path, str]] = []

    # Canonical layout: artifacts/<job_id>/<run_id>/
    for job_dir in artifacts_root.iterdir():
        if not job_dir.is_dir():
            continue
        if job_dir.name in {"runs", ".git"}:
            continue
        for run_dir in job_dir.iterdir():
            if not run_dir.is_dir() or run_dir.name.startswith("."):
                continue
            run_dirs.append((run_dir, "canonical"))

    # Legacy layout: artifacts/runs/<run_id>/
    legacy_runs = artifacts_root / "runs"
    if legacy_runs.exists():
        for run_dir in legacy_runs.iterdir():
            if run_dir.name.startswith("."):
                continue
            if run_dir.is_dir() or run_dir.is_symlink():
                run_dirs.append((run_dir, "legacy"))

    return run_dirs


def _discover_manifests(repo_root: Path) -> Tuple[List[Tuple[Path, str]], int, int, int]:
    run_dirs = _discover_run_dirs(repo_root)

    valid_candidates: List[Tuple[Path, str]] = []
    missing_manifest = 0
    malformed_json = 0
    orphaned_symlinks_detected = 0

    for run_dir, source in run_dirs:
        # Check if this is an orphaned symlink (broken legacy alias)
        # Robust detection: explicitly resolve symlink target and check existence
        if run_dir.is_symlink():
            try:
                symlink_target = run_dir.readlink()
                # Resolve relative targets against symlink's parent
                if not symlink_target.is_absolute():
                    resolved_target = (run_dir.parent / symlink_target).resolve()
                else:
                    resolved_target = symlink_target
                
                # Check if resolved target exists
                if not resolved_target.exists():
                    orphaned_symlinks_detected += 1
                    print(f"WARN orphaned symlink: {run_dir} -> {symlink_target} (target missing)")
                    # Attempt to clean it up
                    try:
                        run_dir.unlink()
                        print(f"  → cleaned up broken symlink")
                    except Exception as e:
                        print(f"  → failed to clean: {e}")
                    continue
            except Exception as e:
                # If we can't read the symlink, treat as orphaned
                orphaned_symlinks_detected += 1
                print(f"WARN unreadable symlink: {run_dir} ({e})")
                try:
                    run_dir.unlink()
                    print(f"  → cleaned up unreadable symlink")
                except Exception as cleanup_err:
                    print(f"  → failed to clean: {cleanup_err}")
                continue
        
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            missing_manifest += 1
            print(f"WARN missing manifest: {run_dir}")
            continue
        try:
            _ = _load_manifest(manifest_path)
        except Exception as exc:
            malformed_json += 1
            print(f"WARN malformed manifest JSON: {manifest_path} ({exc})")
            continue
        valid_candidates.append((manifest_path, source))

    return valid_candidates, missing_manifest, malformed_json, orphaned_symlinks_detected


def _choose_preferred_manifest(
    current: Tuple[Path, str],
    candidate: Tuple[Path, str],
) -> Tuple[Path, str]:
    current_path, current_source = current
    candidate_path, candidate_source = candidate

    if current_source == "canonical" and candidate_source == "legacy":
        return current
    if candidate_source == "canonical" and current_source == "legacy":
        return candidate
    return candidate if str(candidate_path) < str(current_path) else current


def _validate_manifest_integrity(manifest: Dict[str, Any], manifest_path: Path) -> List[str]:
    errors: List[str] = []

    job_id = manifest.get("job_id")
    run_id = manifest.get("run_id")
    inputs_hash = manifest.get("inputs_hash")

    if not job_id:
        errors.append("missing job_id")
    if not run_id:
        errors.append("missing run_id")
    if not inputs_hash:
        errors.append("missing inputs_hash")

    if errors:
        return errors

    # Validate all snapshots declared in manifest.input_snapshots
    manifest_input_snapshots = manifest.get("input_snapshots")
    if not isinstance(manifest_input_snapshots, dict):
        errors.append("missing or invalid input_snapshots metadata")
        return errors
    
    if not manifest_input_snapshots:
        errors.append("input_snapshots is empty")
        return errors

    snapshot_hashes: Dict[str, str] = {}
    for name, snapshot_meta in manifest_input_snapshots.items():
        if not isinstance(snapshot_meta, dict):
            errors.append(f"missing input_snapshots.{name} metadata")
            continue
        
        rel_path = snapshot_meta.get("path")
        if not rel_path:
            errors.append(f"input_snapshots.{name}.path missing")
            continue
        
        snapshot_path = manifest_path.parent / rel_path
        if not snapshot_path.exists():
            errors.append(f"missing snapshot: {rel_path}")
            continue

        snapshot_bytes = snapshot_path.read_bytes()
        snapshot_hash = sha256_bytes(snapshot_bytes)
        snapshot_hashes[name] = snapshot_hash

        if snapshot_meta.get("sha256") != snapshot_hash:
            errors.append(
                f"input_snapshots.{name}.sha256 mismatch (manifest={snapshot_meta.get('sha256')}, recomputed={snapshot_hash})"
            )
        expected_bytes = len(snapshot_bytes)
        if snapshot_meta.get("bytes") != expected_bytes:
            errors.append(
                f"input_snapshots.{name}.bytes mismatch (manifest={snapshot_meta.get('bytes')}, expected={expected_bytes})"
            )

    doctrine = manifest.get("doctrine")
    if not isinstance(doctrine, dict):
        errors.append("missing doctrine metadata")
    else:
        # Load and parse doctrine snapshot to verify governance fields + content hash
        doctrine_snapshot_path = manifest_path.parent / "inputs" / "doctrine.resolved.json"
        if not doctrine_snapshot_path.exists():
            errors.append("doctrine_snapshot_missing")
        else:
            try:
                doctrine_snapshot = json.loads(doctrine_snapshot_path.read_text("utf-8"))
            except Exception as e:
                errors.append(f"doctrine_snapshot_malformed: {e}")
                doctrine_snapshot = {}

            # Validate required schema fields in doctrine snapshot
            for schema_field in ["doctrine_id", "version", "sha256", "content"]:
                if schema_field not in doctrine_snapshot:
                    errors.append(f"doctrine_snapshot_missing_field:{schema_field}")

            # Validate governance fields match manifest.doctrine
            for field in ["doctrine_id", "version"]:
                snapshot_val = doctrine_snapshot.get(field)
                manifest_val = doctrine.get(field)
                if snapshot_val != manifest_val:
                    errors.append(
                        f"doctrine_field_mismatch:{field} (snapshot={snapshot_val}, manifest={manifest_val})"
                    )

            # Verify doctrine.sha256 is consistent between snapshot and manifest
            doc_sha256_in_manifest = doctrine.get("sha256")
            doc_sha256_in_snapshot = doctrine_snapshot.get("sha256")
            if doc_sha256_in_manifest != doc_sha256_in_snapshot:
                errors.append(
                    f"doctrine_field_mismatch:sha256 (snapshot={doc_sha256_in_snapshot}, manifest={doc_sha256_in_manifest})"
                )

            # Recompute doctrine content hash and verify it matches manifest
            doctrine_content = doctrine_snapshot.get("content", "")
            doctrine_content_hash = sha256_bytes(doctrine_content.encode("utf-8"))
            if doc_sha256_in_manifest and doctrine_content_hash != doc_sha256_in_manifest:
                errors.append(
                    f"doctrine_content_hash_mismatch (manifest={doc_sha256_in_manifest}, recomputed={doctrine_content_hash})"
                )

    # Validate inputs_hash derivation from all snapshot hashes
    if len(snapshot_hashes) == len(manifest_input_snapshots):
        recomputed_inputs_hash = compute_inputs_hash(snapshot_hashes)
        if recomputed_inputs_hash != inputs_hash:
            # Check if snapshot or doctrine errors already explain the mismatch
            has_snapshot_errors = any(
                "input_snapshots" in err or "missing snapshot" in err or "doctrine" in err
                for err in errors
            )
            if has_snapshot_errors:
                errors.append(
                    f"inputs_hash mismatch (expected because snapshot bytes changed; manifest={inputs_hash}, recomputed={recomputed_inputs_hash})"
                )
            else:
                errors.append(
                    f"inputs_hash mismatch (manifest={inputs_hash}, recomputed={recomputed_inputs_hash})"
                )

        base_run_id = derive_run_id(inputs_hash)
        if run_id == base_run_id:
            pass
        elif run_id.startswith(base_run_id + "-"):
            suffix = run_id[len(base_run_id) + 1 :]
            if not suffix.isdigit() or int(suffix) < 2:
                errors.append(f"invalid deterministic suffix in run_id: {run_id}")
            else:
                expected = derive_run_id(inputs_hash, suffix)
                if expected != run_id:
                    errors.append(f"run_id derivation mismatch (expected={expected}, actual={run_id})")
        else:
            errors.append(f"run_id does not derive from inputs_hash (base={base_run_id}, actual={run_id})")

    return errors


def _load_manifest(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def reindex(repo_root: Path, verify: bool = False) -> int:
    candidates, missing_manifest_count, malformed_json_count, orphaned_symlinks_count = _discover_manifests(repo_root)

    deduped: Dict[Tuple[str, str], Tuple[Path, str]] = {}
    skipped_missing_fields = 0
    for manifest_path, source in candidates:
        manifest = _load_manifest(manifest_path)
        job_id = manifest.get("job_id")
        run_id = manifest.get("run_id")
        if not job_id or not run_id:
            skipped_missing_fields += 1
            print(f"WARN missing required manifest fields job_id/run_id: {manifest_path}")
            continue
        key = (str(job_id), str(run_id))
        if key not in deduped:
            deduped[key] = (manifest_path, source)
        else:
            deduped[key] = _choose_preferred_manifest(deduped[key], (manifest_path, source))

    print(
        f"Discovered manifests: {len(candidates)}, unique runs: {len(deduped)}, "
        f"missing_manifest: {missing_manifest_count}, malformed_json: {malformed_json_count}, "
        f"missing_required_fields: {skipped_missing_fields}, orphaned_symlinks_detected: {orphaned_symlinks_count}"
    )

    with connect() as conn:
        init_db(conn)

        exec_sql(
            conn,
            """
            CREATE TABLE IF NOT EXISTS run_index (
              job_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              job_ref TEXT,
              job_type TEXT,
              status TEXT,
              inputs_hash TEXT,
              artifact_dir TEXT NOT NULL,
              manifest_json JSONB NOT NULL,
              indexed_at TIMESTAMPTZ NOT NULL,
              PRIMARY KEY (job_id, run_id)
            );
            """,
        )

        indexed = 0
        skipped = 0
        verify_failures = 0

        for (job_id, run_id), (manifest_path, _source) in sorted(deduped.items()):
            manifest = _load_manifest(manifest_path)

            if verify:
                integrity_errors = _validate_manifest_integrity(manifest, manifest_path)
                if integrity_errors:
                    verify_failures += 1
                    skipped += 1
                    print(f"VERIFY FAIL: {manifest_path}")
                    for err in integrity_errors:
                        print(f"  - {err}")
                    continue

            artifact_dir = str(manifest_path.parent.relative_to(repo_root)).replace(os.sep, "/")

            exec_sql(
                conn,
                """
                INSERT INTO run_index (
                  job_id, run_id, job_ref, job_type, status, inputs_hash,
                  artifact_dir, manifest_json, indexed_at
                ) VALUES (
                  :job_id, :run_id, :job_ref, :job_type, :status, :inputs_hash,
                  :artifact_dir, CAST(:manifest_json AS JSONB), :indexed_at
                )
                ON CONFLICT (job_id, run_id)
                DO UPDATE SET
                  job_ref = EXCLUDED.job_ref,
                  job_type = EXCLUDED.job_type,
                  status = EXCLUDED.status,
                  inputs_hash = EXCLUDED.inputs_hash,
                  artifact_dir = EXCLUDED.artifact_dir,
                  manifest_json = EXCLUDED.manifest_json,
                  indexed_at = EXCLUDED.indexed_at;
                """,
                {
                    "job_id": job_id,
                    "run_id": run_id,
                    "job_ref": manifest.get("job_ref"),
                    "job_type": manifest.get("job_type"),
                    "status": manifest.get("status"),
                    "inputs_hash": manifest.get("inputs_hash"),
                    "artifact_dir": artifact_dir,
                    "manifest_json": json.dumps(manifest, ensure_ascii=False),
                    "indexed_at": _utc_now(),
                },
            )
            indexed += 1

    report = (
        f"Indexed: {indexed}, Skipped: {skipped}, Verify failures: {verify_failures if verify else 0}, "
        f"Missing manifests: {missing_manifest_count}, Malformed JSON: {malformed_json_count}, "
        f"Missing required fields: {skipped_missing_fields}, Orphaned symlinks detected: {orphaned_symlinks_count}"
    )
    print(report)

    if verify and (verify_failures > 0 or malformed_json_count > 0 or skipped_missing_fields > 0 or orphaned_symlinks_count > 0):
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex run manifests from filesystem artifacts")
    parser.add_argument("--verify", action="store_true", help="Verify manifest integrity while reindexing")
    args = parser.parse_args()

    repo_root = Path(os.getenv("SIGILZERO_REPO_ROOT", "/app"))
    try:
        return reindex(repo_root, verify=args.verify)
    except Exception as exc:
        print(f"Reindex failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
