#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.jobs import JOB_PIPELINE_REGISTRY, resolve_pipeline
def main() -> int:
    env_repo_root = os.getenv("SIGILZERO_REPO_ROOT")
    repo_root = Path(env_repo_root) if env_repo_root else Path(__file__).resolve().parents[2]
    jobs_root = repo_root / "jobs"

    print("Registry smoke test")
    print(f"repo_root={repo_root}")
    print(f"registry_job_types={sorted(JOB_PIPELINE_REGISTRY.keys())}")

    if not jobs_root.exists():
        print(f"✗ jobs directory not found: {jobs_root}")
        return 1

    missing = []
    checked = 0
    for brief_path in sorted(jobs_root.glob("**/brief.yaml")):
        with brief_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            missing.append((str(brief_path.relative_to(repo_root)), "<invalid-brief>"))
            checked += 1
            continue

        job_type = data.get("job_type", "instagram_copy")
        checked += 1
        if job_type not in JOB_PIPELINE_REGISTRY:
            missing.append((str(brief_path.relative_to(repo_root)), job_type))

    if checked == 0:
        print(f"✗ No brief.yaml files found under {jobs_root}")
        return 1

    if missing:
        print("Missing registry mappings:")
        for path, job_type in missing:
            print(f"  - {path}: job_type={job_type}")
        return 1

    print(f"✓ All {checked} brief.yaml files map to registry entries")

    # Unknown job_type must fail fast with clear error
    try:
        resolve_pipeline("does_not_exist")
        print("✗ Expected unknown job_type to fail fast, but it succeeded")
        return 1
    except ValueError as exc:
        if "Unsupported job_type" not in str(exc):
            print(f"✗ Unknown job_type raised unexpected error: {exc}")
            return 1
        print(f"✓ Unknown job_type fails fast: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
