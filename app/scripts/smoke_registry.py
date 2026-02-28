#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.jobs import JOB_PIPELINE_REGISTRY, resolve_pipeline
from sigilzero.core.schemas import BriefSpec


def main() -> int:
    repo_root = Path(os.getenv("SIGILZERO_REPO_ROOT", "/app"))
    jobs_root = repo_root / "jobs"

    print("Registry smoke test")
    print(f"repo_root={repo_root}")
    print(f"registry_job_types={sorted(JOB_PIPELINE_REGISTRY.keys())}")

    missing = []
    checked = 0
    for brief_path in sorted(jobs_root.glob("**/brief.yaml")):
        with brief_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        brief = BriefSpec.model_validate(data)
        checked += 1
        if brief.job_type not in JOB_PIPELINE_REGISTRY:
            missing.append((str(brief_path.relative_to(repo_root)), brief.job_type))

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
