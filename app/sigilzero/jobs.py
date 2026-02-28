from __future__ import annotations

import os
from rq import Queue
from redis import Redis
from typing import Any, Dict, Optional

import yaml  # type: ignore

from .core.schemas import BriefSpec
from .pipelines.phase0_instagram_copy import execute_instagram_copy_pipeline


def get_redis() -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


def get_queue() -> Queue:
    return Queue("sigilzero", connection=get_redis())


def execute_job(repo_root: str, job_ref: str, params: Optional[Dict[str, Any]] = None) -> str:
    """RQ job target: dispatches by job_type found in brief.yaml and returns run_id."""
    full = os.path.join(repo_root, job_ref)
    with open(full, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    brief = BriefSpec.model_validate(data)
    if brief.job_type == "instagram_copy":
        return execute_instagram_copy_pipeline(repo_root, job_ref, params=params)
    raise ValueError(f"Unsupported job_type: {brief.job_type}")


def enqueue_job(repo_root: str, job_ref: str, params: Optional[Dict[str, Any]] = None):
    q = get_queue()
    return q.enqueue(execute_job, repo_root, job_ref, params or {})
