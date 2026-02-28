from __future__ import annotations

import os
from rq import Queue, get_current_job
from redis import Redis
from typing import Any, Dict, Optional

import yaml  # type: ignore

from .core.schemas import BriefSpec
from .pipelines.phase0_instagram_copy import execute_instagram_copy_pipeline


JOB_PIPELINE_REGISTRY = {
    "instagram_copy": execute_instagram_copy_pipeline,
}


def get_redis() -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


def get_queue() -> Queue:
    return Queue("sigilzero", connection=get_redis())


def execute_job(repo_root: str, job_ref: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """RQ job target: dispatches by job_type found in brief.yaml.
    
    Phase 1.0: Returns dict with run_id and other metadata.
    Passes queue_job_id (RQ UUID) to pipeline for manifest tracking.
    """
    params = params or {}
    
    # Phase 1.0: Get RQ job ID (ephemeral queue identifier)
    current_job = get_current_job()
    if current_job:
        params["queue_job_id"] = current_job.id
    
    full = os.path.join(repo_root, job_ref)
    with open(full, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    brief = BriefSpec.model_validate(data)
    
    pipeline_fn = JOB_PIPELINE_REGISTRY.get(brief.job_type)
    if pipeline_fn is None:
        raise ValueError(f"Unsupported job_type: {brief.job_type}")

    return pipeline_fn(repo_root, job_ref, params=params)


def enqueue_job(repo_root: str, job_ref: str, params: Optional[Dict[str, Any]] = None):
    q = get_queue()
    return q.enqueue(execute_job, repo_root, job_ref, params or {})
