#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path
from typing import List


def _find_tmp_dirs(repo_root: Path) -> List[Path]:
    artifacts_root = repo_root / "artifacts"
    if not artifacts_root.exists():
        return []

    tmp_dirs: List[Path] = []

    legacy_tmp = artifacts_root / "runs" / ".tmp"
    if legacy_tmp.exists():
        for p in legacy_tmp.glob("tmp-*"):
            if p.is_dir():
                tmp_dirs.append(p)

    for job_dir in artifacts_root.iterdir():
        if not job_dir.is_dir() or job_dir.name == "runs":
            continue
        job_tmp = job_dir / ".tmp"
        if job_tmp.exists():
            for p in job_tmp.glob("tmp-*"):
                if p.is_dir():
                    tmp_dirs.append(p)

    return sorted(tmp_dirs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup stale tmp run directories")
    parser.add_argument("--hours", type=float, default=6.0, help="Delete tmp-* older than N hours")
    args = parser.parse_args()

    repo_root = Path(os.getenv("SIGILZERO_REPO_ROOT", "/app"))
    cutoff = time.time() - args.hours * 3600

    candidates = _find_tmp_dirs(repo_root)
    removed = 0
    kept = 0

    for tmp_dir in candidates:
        mtime = tmp_dir.stat().st_mtime
        if mtime < cutoff:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            removed += 1
            print(f"REMOVED {tmp_dir}")
        else:
            kept += 1
            print(f"KEPT {tmp_dir}")

    print(f"Cleanup summary: removed={removed}, kept={kept}, threshold_hours={args.hours}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
