from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, Connection


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        # Sensible default for local docker-compose (user can override via env)
        url = "postgresql+psycopg2://postgres:postgres@postgres:5432/postgres"
    # Ensure SQLAlchemy dialect prefix exists
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


_ENGINE: Optional[Engine] = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(get_database_url(), pool_pre_ping=True)
    return _ENGINE


@contextmanager
def connect() -> Iterator[Connection]:
    eng = get_engine()
    with eng.begin() as conn:
        yield conn


def exec_sql(conn: Connection, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
    conn.execute(text(sql), params or {})


def fetch_one(conn: Connection, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    res = conn.execute(text(sql), params or {}).mappings().first()
    return dict(res) if res else None


def fetch_all(conn: Connection, sql: str, params: Optional[Dict[str, Any]] = None) -> list[Dict[str, Any]]:
    res = conn.execute(text(sql), params or {}).mappings().all()
    return [dict(r) for r in res]


def init_db(conn: Connection) -> None:
    """Create minimal tables if they don't exist."""
    # Runs
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY,
      pipeline_id TEXT NOT NULL,
      pipeline_version TEXT NOT NULL,
      status TEXT NOT NULL,
      release_ref TEXT NOT NULL,
      release_hash TEXT,
      repo_commit TEXT,
      created_at TIMESTAMPTZ NOT NULL,
      started_at TIMESTAMPTZ,
      finished_at TIMESTAMPTZ,
      error TEXT
    );
    """)
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS run_steps (
      run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
      step_name TEXT NOT NULL,
      step_version TEXT NOT NULL,
      status TEXT NOT NULL,
      deterministic BOOLEAN NOT NULL,
      cacheable BOOLEAN NOT NULL,
      cache_hit BOOLEAN NOT NULL DEFAULT FALSE,
      input_hash TEXT NOT NULL,
      output_hash TEXT,
      started_at TIMESTAMPTZ NOT NULL,
      finished_at TIMESTAMPTZ,
      langfuse_trace_id TEXT,
      langfuse_span_id TEXT,
      error TEXT,
      PRIMARY KEY (run_id, step_name, started_at)
    );
    """)
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS context_specs (
      context_spec_hash TEXT PRIMARY KEY,
      context_spec_json JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL
    );
    """)
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS context_packs (
      pack_hash TEXT PRIMARY KEY,
      context_spec_hash TEXT NOT NULL REFERENCES context_specs(context_spec_hash) ON DELETE CASCADE,
      pack_json JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL
    );
    """)
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS generations (
      generation_hash TEXT PRIMARY KEY,
      generation_spec_json JSONB NOT NULL,
      raw_response_text TEXT,
      parsed_response_json JSONB,
      created_at TIMESTAMPTZ NOT NULL
    );
    """)
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS artifacts (
      artifact_hash TEXT PRIMARY KEY,
      run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
      logical_name TEXT NOT NULL,
      path TEXT NOT NULL,
      kind TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL
    );
    """)
    exec_sql(conn, """
    CREATE TABLE IF NOT EXISTS run_manifests (
      run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
      manifest_hash TEXT NOT NULL,
      manifest_json JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL
    );
    """)
