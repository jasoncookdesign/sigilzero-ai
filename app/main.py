from fastapi import FastAPI
from pydantic import BaseModel
import os

app = FastAPI(title="SIGIL.ZERO AI")

class HealthResponse(BaseModel):
    status: str

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")

@app.get("/")
def root():
    return {"message": "SIGIL.ZERO deterministic governance engine online"}