from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os

from sigilzero.jobs import enqueue_job

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
    repo_root = os.getenv("SIGILZERO_REPO_ROOT", "/app")

    full = os.path.join(repo_root, req.job_ref)
    if not os.path.isfile(full):
        raise HTTPException(status_code=400, detail=f"job_ref not found at {full}")

    job = enqueue_job(repo_root, req.job_ref, req.params or {})
    return JobRunResponse(job_id=job.id, run_id=(req.params or {}).get("run_id"))
