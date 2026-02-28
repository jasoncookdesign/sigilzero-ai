from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import yaml

from sigilzero.jobs import enqueue_job
from sigilzero.core.schemas import BriefSpec

app = FastAPI(title="SIGIL.ZERO AI")


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.get("/")
def root():
    return {"message": "SIGIL.ZERO deterministic governance engine online"}


class JobRunRequest(BaseModel):
    job_ref: str
    params: dict | None = None


class JobRunResponse(BaseModel):
    job_id: str
    run_id: str | None = None


@app.post("/jobs/run", response_model=JobRunResponse)
def run_job(req: JobRunRequest):
    """Enqueue a job for execution.
    
    Phase 1.0 Governance: Returns job_id from brief (governance identifier),
    not RQ queue UUID. The queue UUID is recorded in manifest as queue_job_id.
    """
    repo_root = os.getenv("SIGILZERO_REPO_ROOT", "/app")

    full = os.path.join(repo_root, req.job_ref)
    if not os.path.isfile(full):
        raise HTTPException(status_code=400, detail=f"job_ref not found at {full}")

    # Phase 1.0: Load brief to get governance job_id
    try:
        with open(full, "r", encoding="utf-8") as f:
            brief_data = yaml.safe_load(f) or {}
        brief = BriefSpec.model_validate(brief_data)
        governance_job_id = brief.job_id
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse brief: {e}")

    # Enqueue job (returns RQ Job object with queue UUID)
    rq_job = enqueue_job(repo_root, req.job_ref, req.params or {})
    
    # Return governance job_id (from brief), run_id is null until job executes
    return JobRunResponse(job_id=governance_job_id, run_id=None)
