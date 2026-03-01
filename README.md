# SIGIL.ZERO AI

## 1) Project Overview

SIGIL.ZERO AI is a production-oriented orchestration system for governed AI jobs with deterministic artifact generation.  
It is built around a strict contract:

- Canonical inputs are snapshotted to disk before execution.
- Run identity is derived from those snapshots.
- Filesystem artifacts are the source of truth.
- Database state is an index/cache that can be rebuilt.

This repository is for engineers operating and extending deterministic AI pipelines (for example, brand optimization/compliance workflows) where reproducibility, auditability, and governance traceability are required.

---

## 2) Core Design Principles

### Canonical input snapshots
Each run persists frozen inputs under:

- `inputs/brief.resolved.json`
- `inputs/context.resolved.json`
- `inputs/model_config.json`
- `inputs/doctrine.resolved.json` (when doctrine applies)
- stage-specific additional snapshots (for chainable stages, e.g. prior artifact metadata)

Hashes are computed from on-disk snapshot bytes, not in-memory objects.

### Deterministic `run_id` derivation
`run_id` is derived from `inputs_hash`, where `inputs_hash` is computed from snapshot hashes only.  
Collision suffixes (if used) are deterministic (`-2`, `-3`, ...).

### Governance `job_id` vs queue `queue_job_id`
- `job_id`: governance identity from brief input.
- `queue_job_id`: queue/runtime execution identifier (e.g., RQ UUID), tracked separately.

### Doctrine as versioned, hashed input
Doctrine is loaded as versioned in-repo content, snapshotted, hashed, and included in `inputs_hash`.  
Manifest records doctrine identifiers and hashes.

### Filesystem-authoritative persistence
`manifest.json` + artifacts are canonical.  
Postgres (or other DB) is index/cache-only and must be rebuildable from artifacts (reindex flow).

### No silent drift
Any change in canonical inputs must change `inputs_hash`; any change in `inputs_hash` must change `run_id`.  
Smoke tests and verifier utilities enforce this chain.

### Backward compatibility
- `/jobs/run` API contract remains stable.
- `job_ref` semantics remain stable.
- Existing artifacts/manifests (including historical instagram_copy outputs) remain readable.

---

## 3) Architecture Overview

### High-level flow

```text
Client/API
  |
  v
/jobs/run  --> registry dispatch (app/sigilzero/jobs.py)
  |
  v
Pipeline execution
  |-- resolve inputs
  |-- write canonical snapshots (inputs/*.json)
  |-- hash snapshots
  |-- compute inputs_hash
  |-- derive run_id
  |-- idempotent replay check
  |-- execute stage logic
  |-- write outputs/*
  |-- write canonical manifest.json
  |
  v
Optional DB indexing (rebuildable from artifacts)
```

### Artifact layout

```text
artifacts/
  <job_id>/
    <run_id>/
      inputs/
        brief.resolved.json
        context.resolved.json
        model_config.json
        doctrine.resolved.json          # when applicable
        prior_artifact.resolved.json    # chainable stages
      outputs/
        ... stage outputs ...
      manifest.json
```

### Manifest expectations
`manifest.json` records run metadata, snapshot paths/hashes/bytes, `inputs_hash`, and output metadata.

Deterministic serialization excludes nondeterministic fields (notably runtime timestamps and observability trace IDs).

### `inputs_hash` / `run_id`
- `inputs_hash` is recomputed from manifest-declared snapshot hashes (deterministic ordering).
- `run_id` derives from `inputs_hash` (plus deterministic collision suffix when needed).

### Chainable model
Later stages can consume a previous artifact snapshot (`prior_artifact.resolved.json`) as canonical input.  
That snapshot participates in `inputs_hash`, so upstream output changes propagate deterministically downstream.

---

## 4) Pipeline System

### Registry-based routing
Job dispatch is explicit and code-defined in:

- `app/sigilzero/jobs.py`

No dynamic import-by-string routing for governed job execution paths.

### Adding and wiring pipelines
Pipelines are implemented under `app/sigilzero/pipelines/` and registered through the central job registry adapters to preserve existing `execute_job(...)` shape and API behavior.

### Chainable stages
Chainable stages include prior-artifact metadata in canonical inputs.  
Verifier logic validates chainable snapshot requirements and structure.

### Idempotent replay
If an artifact directory already exists for the same canonical inputs, reruns should replay/idempotently return existing identity instead of creating divergent logical runs.

---

## 5) Determinism & Verification

Main module:

- `app/sigilzero/core/determinism.py`

Key components:

### `SnapshotValidator`
Validates snapshot presence and hash integrity against manifest metadata.

### `DeterminismVerifier`
Validates determinism invariants at artifact level, including:

- snapshot presence
- snapshot hash consistency
- `inputs_hash` recomputation from manifest snapshot set
- `run_id` derivation checks
- governance `job_id` consistency
- chainable requirements (when stage is chainable)

### `replay_run_idempotent`
Checks rerun/idempotency behavior from existing artifacts.

### Deterministic serialization boundaries
Nondeterministic fields are excluded from deterministic manifest serialization (for byte-stable deterministic comparisons), including:

- `started_at`
- `finished_at`
- `langfuse_trace_id`

These fields may exist in runtime models but do not participate in deterministic manifest bytes.

### Validate an artifact
Use smoke and verifier scripts (examples in section 8) to assert:

- canonical snapshots exist
- hashes match bytes
- `inputs_hash` and `run_id` are consistent
- deterministic serialization output is stable

---

## 6) Schema Versioning & Migrations

Core modules/scripts:

- `app/sigilzero/core/schemas.py`
- `app/sigilzero/core/migrations.py`
- `app/scripts/migrate_schemas.py`
- `app/scripts/smoke_schema_migrations.py`

### Strategy
Schema evolution is explicit and versioned; migrations are artifact-first and preserve determinism-critical identity fields.

### Guarantees
Migrations are designed to preserve:

- `job_id`
- `run_id`
- canonical input snapshots and snapshot hashes

### Migration safety
- idempotent execution
- backup creation before write
- dry-run support (no write mode)
- migration history tracking in manifest schema (`migration_history`)

### Running migrations
Use the migration CLI to migrate artifact manifests across schema versions, then run smoke validation scripts.

---

## 7) Observability

Primary files:

- `app/sigilzero/core/langfuse_client.py`
- `app/sigilzero/core/observability.py`
- `app/scripts/smoke_observability.py`

### Langfuse integration
Observability spans/traces are integrated without changing deterministic run identity.

### Determinism boundary
Trace identifiers are excluded from deterministic manifest serialization (`langfuse_trace_id` excluded).  
Observability must not influence snapshot hashes, `inputs_hash`, or `run_id`.

### Failure mode
Observability failures are designed to degrade gracefully (non-fatal to core artifact generation path), validated by smoke tests.

---

## 8) CLI Utilities & Scripts

Common scripts in `app/scripts/`:

- `smoke_determinism.py` — determinism invariants smoke checks
- `smoke_registry.py` — registry routing coverage checks
- `smoke_schema_migrations.py` — migration integrity/idempotency checks
- `smoke_observability.py` — observability determinism + graceful-failure checks
- `smoke_release_candidate_hardening.py` — Stage 12 hardening suite
- `migrate_schemas.py` — schema migration CLI

### Reindex behavior
DB/index state is rebuildable from filesystem artifacts. Reindex should be treated as derivation from manifests/artifacts, not source-of-truth mutation.

### Verify mode
Verification is performed via smoke scripts and determinism verifier APIs; use dry-run/verify semantics where provided by each script/command.

---

## 9) Development Setup

### Runtime
- Python: use the version required by repository tooling (typically 3.11+ for current dependencies).
- Dependencies: `app/requirements.txt`

### Install

```bash
cd /Users/jcodec/Sites/SIGIL.ZERO\ AI/sigilzero-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
```

### Environment variables
Configure provider/API keys and runtime settings as required by your local pipeline execution and observability setup (Langfuse, model providers, DB/index if used).

### Run smoke tests

```bash
python3 app/scripts/smoke_registry.py
python3 app/scripts/smoke_determinism.py
python3 app/scripts/smoke_schema_migrations.py
python3 app/scripts/smoke_observability.py
python3 app/scripts/smoke_release_candidate_hardening.py
```

### Run pipelines locally
Use existing job entrypoints (`/jobs/run` in service mode or local execution paths in `app/sigilzero/jobs.py`) with valid briefs and repository-root-aware paths.

### Directory expectations
Repository assumes artifact persistence under `artifacts/<job_id>/<run_id>/...` and doctrine files available in-repo for governed resolution.

---

## 10) Adding a New Pipeline

1. **Define/extend schema**
   - Add/extend typed models in `app/sigilzero/core/schemas.py`.
   - Ensure nondeterministic fields are excluded from deterministic serialization if needed.

2. **Resolve and snapshot inputs**
   - Write canonical snapshots to `inputs/` before processing.
   - Use stable JSON serialization (`sort_keys=True`, deterministic formatting).

3. **Hash snapshots**
   - Compute per-snapshot SHA256 from on-disk bytes.
   - Record snapshot path/hash/size in manifest snapshot metadata.

4. **Compute `inputs_hash`**
   - Derive only from snapshot hashes (deterministic ordering).

5. **Derive `run_id`**
   - Derive from `inputs_hash`.
   - If collision resolution is necessary, use deterministic suffixing.

6. **Execute stage + write outputs**
   - Persist outputs under `outputs/`.
   - For chainable stages, snapshot prior artifact metadata as canonical input.

7. **Write canonical manifest**
   - Persist deterministic manifest JSON.
   - Keep governance IDs and doctrine metadata complete and consistent.

8. **Register job type**
   - Add pipeline dispatch in `app/sigilzero/jobs.py` registry.

9. **Add smoke coverage**
   - Add/extend `smoke_*` checks for determinism, schema, and routing.

---

## 11) Release Process

### Determinism checklist
- Canonical snapshots present and byte-stable.
- Snapshot hashes match on-disk bytes.
- `inputs_hash` recomputes from manifest snapshot set.
- `run_id` matches derivation rules.
- Nondeterministic fields excluded from deterministic serialization.

### Schema migration checklist
- Backups enabled.
- Dry-run reviewed.
- Idempotency verified.
- `run_id`/`job_id` unchanged after migration.
- Smoke migration suite passes.

### Backward compatibility checklist
- `/jobs/run` response contract unchanged.
- `job_ref` behavior unchanged.
- Existing artifact/manifests still load and validate.
- Registry changes do not break in-repo job types.

---

## 12) License / Contribution

- License: add/confirm repository license file.
- Contributions: open PRs with:
  - deterministic artifact impacts documented,
  - smoke tests added/updated,
  - migration notes included for schema changes,
  - backward-compatibility assessment included in PR description.