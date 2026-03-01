# Stage 12: Release Candidate Hardening

## Objective
Implement final-stage hardening while preserving:
- Snapshot-based canonical inputs
- Deterministic run_id derivation
- Governance-level job_id
- Filesystem-authoritative persistence
- Code-defined registry routing
- Versioned doctrine loading with hashed content
- Backward-compatible API surface

---

## Architectural Enforcement Addendum (Implemented)

### 1) Canonical Input Snapshots
Enforced canonical snapshot files under each run directory:
- `inputs/brief.resolved.json`
- `inputs/context.resolved.json`
- `inputs/model_config.json`
- `inputs/doctrine.resolved.json`

Implementation behavior:
- Snapshots are written before processing.
- Snapshot hashes are computed from on-disk bytes.
- `inputs_hash` is computed only from snapshot hashes.
- JSON serialization uses deterministic formatting (`sort_keys=True`, stable indent/newline).

### 2) Deterministic `run_id`
Enforced deterministic run identity:
- `run_id` derives from `inputs_hash`.
- Deterministic collision suffix semantics (`-2`, `-3`, …) when needed.
- Idempotent replay returns existing run for matching `inputs_hash`.

### 3) Governance-Level `job_id`
Enforced governance identity separation:
- `job_id` comes from brief governance data.
- Queue identifier is distinct and recorded as `queue_job_id` in runtime model.

### 4) Doctrine as Hashed Input
Enforced doctrine governance input rules:
- Doctrine snapshot is versioned and persisted under `inputs/doctrine.resolved.json`.
- Doctrine content hash is computed and verified.
- Manifest doctrine reference records doctrine id, version, and doctrine content hash.

### 5) Filesystem Authoritative
Enforced source-of-truth boundary:
- Artifacts + manifest are authoritative.
- Reindex remains the path to rebuild DB index state from artifacts.
- Runtime and observability metadata do not alter input snapshot hashing.

### 6) No Silent Drift
Enforced determinism linkage:
- Input snapshot changes change `inputs_hash`.
- `inputs_hash` changes change `run_id` (base or deterministic suffix).
- Stage 12 smoke verifies these links and fails on drift.

### 7) Backward Compatibility
Preserved compatibility requirements:
- `/jobs/run` contract remains unchanged.
- `job_ref` semantics remain unchanged.
- Existing artifact layout compatibility remains intact.

---

## Structural Changes Summary

### Registry hardening
- Completed job type registry routing in `app/sigilzero/jobs.py`:
  - Added `brand_compliance_score`
  - Added `brand_optimization`
- Added adapter functions to preserve existing `execute_job(repo_root, job_ref, params)` dispatch shape.

### Brand optimization hardening
- Updated `app/sigilzero/pipelines/phase0_brand_optimization.py`:
  - Added `params` support and `queue_job_id` capture.
  - Corrected doctrine content hash recording in manifest doctrine reference.
  - Added deterministic collision/idempotent replay behavior aligned with Phase 1.0 semantics.
  - Ensured fresh runs create canonical `inputs/` + `outputs/` paths.
  - Switched manifest persistence to canonical deterministic JSON writer.

### Manifest write canonicalization consistency
- Updated `app/sigilzero/pipelines/phase0_brand_compliance_score.py` to use canonical deterministic manifest writing.

### Stage 12 smoke validation
- Added `app/scripts/smoke_release_candidate_hardening.py` with checks for:
  - Registry coverage across all in-repo briefs.
  - Canonical snapshot presence + canonical JSON formatting.
  - Snapshot hash/byte verification against manifest metadata.
  - `inputs_hash` recomputation from snapshot hashes only.
  - `run_id` derivation validation (base or deterministic suffix).
  - Doctrine version/hash consistency between snapshot and manifest.
  - Deterministic manifest serialization exclusion for nondeterministic fields.

---

## Determinism Validation

Validated in Stage 12 smoke:
1. Snapshot files exist at canonical paths.
2. Snapshot bytes match canonical JSON representation.
3. Manifest snapshot metadata (`sha256`, `bytes`) matches recomputed file values.
4. `inputs_hash == compute_inputs_hash(snapshot_hashes)`.
5. `run_id == derive_run_id(inputs_hash)` or deterministic suffix equivalent.
6. Manifest deterministic serialization excludes nondeterministic trace/timestamp fields.

---

## Governance Alignment

Validated governance rules:
- `job_id` in manifest matches brief governance identifier.
- Queue job UUID remains separated as `queue_job_id` runtime metadata.
- Doctrine metadata in manifest is aligned with doctrine snapshot content.

---

## Backward Compatibility Confirmation

Confirmed compatibility boundaries:
- `/jobs/run` request/response model unchanged.
- `job_ref` path semantics unchanged.
- Existing brief + artifact layouts remain accepted.
- Registry behavior is stricter and explicit, but compatible with existing in-repo jobs.

---

## Filesystem Authority Confirmation

Confirmed artifact-first model:
- Canonical snapshots and `manifest.json` remain filesystem source of truth.
- Hashing and run identity are derived from filesystem snapshots.
- DB remains index/cache role and can be rebuilt via artifact reindex flow.

---

## Definition of Done (Stage 12)

- [x] No silent drift between snapshots → inputs_hash → run_id.
- [x] API compatibility preserved.
- [x] Manifest contains snapshot paths + hashes.
- [x] Run reproducible from snapshot directory alone.
- [x] Registry-based routing enforced for all in-repo job types.
- [x] Doctrine version + content hash recorded and validated.
- [x] Stage 12 smoke added for explicit enforcement.

---

## Architect Reporting Block

### 1. Structural changes summary
- Registry expanded and normalized through adapters.
- Brand optimization collision/idempotency and governance metadata hardened.
- Manifest write canonicalization aligned in non-instagram pipeline.
- New Stage 12 hardening smoke added.

### 2. Determinism validation
- Snapshot canonicalization, hash recomputation, inputs_hash derivation, and run_id derivation are explicitly tested.

### 3. Governance alignment
- `job_id` from brief is preserved and validated.
- Queue ID remains separate runtime metadata.
- Doctrine governance fields and content hash consistency validated.

### 4. Backward compatibility confirmation
- `/jobs/run` contract and `job_ref` semantics unchanged.
- Existing briefs and artifact conventions remain valid.

### 5. Filesystem authority confirmation
- Filesystem snapshots + manifest are authoritative.
- Hash and run identity derive from on-disk snapshots.
- Reindex model remains compatible with artifact-first authority.
