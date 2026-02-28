#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.core.db import connect, exec_sql, init_db


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _discover_manifests(repo_root: Path) -> List[Path]:
    artifacts_root = repo_root / "artifacts"
    if not artifacts_root.exists():
        return []

    manifests: List[Path] = []

    # Canonical layout: artifacts/<job_id>/<run_id>/manifest.json
    for manifest in artifacts_root.glob("*/*/manifest.json"):
        if not manifest.is_file():
            continue
        parent_job = manifest.parents[1].name
        if parent_job == "runs":
            continue
        manifests.append(manifest)

    # Legacy layout: artifacts/runs/<run_id>/manifest.json
    legacy_runs = artifacts_root / "runs"
    if legacy_runs.exists():
        manifests.extend([p for p in legacy_runs.glob("*/manifest.json") if p.is_file()])

    # Dedupe by resolved path so symlinked legacy entries don't double-index
    unique: Dict[str, Path] = {}
    for manifest in manifests:
        unique[str(manifest.resolve())] = manifest.resolve()
    return sorted(unique.values())


def _load_manifest(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def reindex(repo_root: Path) -> int:
    manifests = _discover_manifests(repo_root)
    print(f"Discovered {len(manifests)} manifest(s) under {repo_root / 'artifacts'}")

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
        for manifest_path in manifests:
            try:
                manifest = _load_manifest(manifest_path)
            except Exception as exc:
                skipped += 1
                print(f"SKIP unreadable manifest: {manifest_path} ({exc})")
                continue

            job_id = manifest.get("job_id")
            run_id = manifest.get("run_id")
            if not job_id or not run_id:
                skipped += 1
                print(f"SKIP invalid manifest (missing job_id/run_id): {manifest_path}")
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

    print(f"Indexed: {indexed}, Skipped: {skipped}")
    return 0


def main() -> int:
    repo_root = Path(os.getenv("SIGILZERO_REPO_ROOT", "/app"))
    try:
        return reindex(repo_root)
    except Exception as exc:
        print(f"Reindex failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
