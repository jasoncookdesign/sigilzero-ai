""" 
ARCHITECTURE_PHASE_1.0_DETERMINISM.md - Phase 1.0 Determinism Guardrails

# Phase 1.0 Determinism Guardrails - Complete Architecture

## Executive Summary

Phase 1.0 enforces NON-NEGOTIABLE determinism invariants across the entire job execution pipeline. These invariants ensure:

1. **Reproducibility**: Identical inputs always produce identical run_id and outputs
2. **Auditable Governance**: job_id comes from governance briefs, not ephemeral queue identifiers
3. **Filesystem Authoritative**: Artifacts + manifest are source of truth; DB is index-only
4. **No Silent Drift**: Any input change immediately changes run_id through inputs_hash
5. **Backward Compatible**: Existing /jobs/run API and artifact structures remain valid

---

## Invariant 1: Canonical Input Snapshots

### Requirement
All inputs MUST be written to disk as deterministic JSON files BEFORE hashing or processing.

### Implementation

#### File Locations (Canonical)
```
artifacts/<job_id>/<run_id>/
├── inputs/
│   ├── brief.resolved.json          # Job specification snapshot
│   ├── context.resolved.json        # Context pack snapshot (query results + content)
│   ├── model_config.json            # LLM configuration snapshot
│   ├── doctrine.resolved.json       # Versioned doctrine snapshot
│   └── prior_artifact.resolved.json # (Chainable only) Prior stage output snapshot
├── outputs/
│   ├── instagram_copy.md            # Main artifact
│   ├── variants/
│   │   └── variants.json            # (Stage 5) All deterministic variants
│   └── ...
└── manifest.json                    # Canonical metadata + audit trail
```

#### Snapshot Format Requirements

**1. brief.resolved.json**
- Contains BriefSpec model dumped to dict with fields excluded for backward compatibility
- Excluded fields: generation_mode, caption_variants, output_formats, context_mode fields IF at defaults AND not explicitly set
- Example:
```json
{
  "job_id": "ig-test-001",
  "job_type": "instagram_copy",
  "brand": "SIGIL.ZERO",
  "tone_tags": ["authentic", "innovative"],
  "constraints": {},
  "ig": { "caption_count": 5, ... }
}
```

**2. context.resolved.json**
```json
{
  "spec": {
    "strategy": "glob" | "retrieve",
    "query": "optional query for retrieve mode",
    "retrieval_config": { ... },
    "selected_items": [ ... ]
  },
  "content": "Raw context text from corpus",
  "content_hash": "sha256:..."
}
```

**3. model_config.json**
```json
{
  "provider": "openai",
  "model": "gpt-4-turbo",
  "temperature": 0.3,
  "top_p": 1.0,
  "response_schema": "response_schemas/ig_copy_package",
  "cache_enabled": true
}
```

**4. doctrine.resolved.json**
```json
{
  "doctrine_id": "prompts/instagram_copy",
  "version": "v1.0.0",
  "sha256": "sha256:...",
  "resolved_path": "sigilzero/prompts/instagram_copy/v1.0.0/template.md"
}
```

**5. prior_artifact.resolved.json** (Chainable only)
```json
{
  "prior_run_id": "d79bbc34291a40a4b0f6faa67e10fc2a",
  "prior_stage": "brand_compliance_score",
  "prior_job_id": "brand-score-001",
  "prior_manifest": {
    "job_id": "brand-score-001",
    "run_id": "d79bbc34291a40a4b0f6faa67e10fc2a",
    "inputs_hash": "sha256:..."
  },
  "required_outputs": ["compliance_scores.json"],
  "prior_output_hashes": {
    "compliance_scores.json": "sha256:..."
  }
}
```

#### JSON Serialization Contract
All snapshots MUST use:
- `sort_keys=True` for deterministic key ordering
- `ensure_ascii=False` to preserve Unicode without escaping
- `indent=2` for readability (stable whitespace)
- Trailing newline enforced

Python implementation:
```python
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def write_json(path: Path, data: Any) -> None:
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)
    if not json_str.endswith("\n"):
        json_str += "\n"
    path.write_text(json_str, encoding="utf-8")
```

### Verification
See `SnapshotValidator` in `sigilzero/core/determinism.py`:
- `validate_run_directory()` - Checks all required snapshots exist
- `validate_snapshot_hashes()` - Verifies snapshots match manifest records

---

## Invariant 2: Deterministic run_id

### Requirement
`run_id` MUST be derived ONLY from `inputs_hash`. No randomness. No wall-clock timestamps.

### Implementation

#### Derivation Chain
```
[Snapshot Files] 
    ↓ hash each
[Snapshot Hashes] = {
    "brief": "sha256:abc123...",
    "context": "sha256:def456...",
    "model_config": "sha256:ghi789...",
    "doctrine": "sha256:jkl012...",
    "prior_artifact": "sha256:mno345..." (if chainable)
}
    ↓ compute_inputs_hash() [sort keys alphabetically, combine]
[inputs_hash] = "sha256:xyz789..."
    ↓ derive_run_id() [extract first 32 hex chars]
[run_id] = "xyz789abc123def456ghi789jkl012mno"
```

#### Algorithm
```python
def compute_inputs_hash(snapshot_hashes: Dict[str, str]) -> str:
    """Deterministic hash from all input snapshot hashes."""
    sorted_items = sorted(snapshot_hashes.items())  # Alphabetical order
    combined = canonical_json(dict(sorted_items))
    return sha256_text(combined)

def derive_run_id(inputs_hash: str, suffix: str = "") -> str:
    """Derive run_id from inputs_hash (no collision handling)."""
    if inputs_hash.startswith("sha256:"):
        hex_hash = inputs_hash[7:]  # Strip prefix
    else:
        hex_hash = inputs_hash
    
    run_id = hex_hash[:32]  # 128 bits (UUID-equivalent entropy)
    if suffix:
        run_id = f"{run_id}-{suffix}"
    return run_id
```

#### Idempotent Replay

If inputs haven't changed:
```python
existing_run_dir = artifacts/<job_id>/<base_run_id>/
if existing_run_dir.exists():
    existing_manifest = load(existing_run_dir / manifest.json)
    if existing_manifest["inputs_hash"] == computed_inputs_hash:
        # Deterministic replay: use existing run_id, return idempotent status
        return ExistingManifest
    # Else: Different inputs → collision, don't execute (error condition)
else:
    # New run
    final_run_dir = artifacts/<job_id>/<base_run_id>/
    execute() → emit outputs → write manifest
```

---

## Invariant 3: Governance-Level job_id

### Requirement
`job_id` MUST come from `brief.yaml` (governance identifier).
Queue identity (`queue_job_id`) MUST be recorded separately as ephemeral.

### Implementation

#### job_id: Governance
- Source: `brief.job_id` (human-assigned from jobs/ briefs)
- Canonical directory structure: `artifacts/<job_id>/<run_id>/`
- Immutable for lifetime of artifact
- Example: `ig-test-001`, `brand-score-001`

#### queue_job_id: Ephemeral
- Source: RQ job UUID from queue (if enqueued)
- Used for queue monitoring & correlation only
- May be null if run executed outside queue
- Recorded in manifest for audit trail
- NOT used in path construction

#### API Contract Preservation

POST /jobs/run returns:
```json
{
  "job_id": "ig-test-001",     // From brief (governance)
  "run_id": null                // Computed after execution
}
```

### Verification
In manifest construction:
```python
manifest = RunManifest(
    job_id=brief.job_id,          # From governance brief
    run_id=run_id,                # Deterministically computed
    queue_job_id=params.get("queue_job_id"),  # Ephemeral queue UUID
    ...
)
```

---

## Invariant 4: Doctrine as Hashed Input

### Requirement
Doctrine files are versioned in-repo. Doctrine content is hashed. Doctrine hash participates in inputs_hash.

### Implementation

#### Doctrine Registry
Allowed doctrine IDs (whitelist):
```python
ALLOWED_DOCTRINE_IDS = {
    "prompts/instagram_copy",
    "prompts/brand_compliance_score",
    "prompts/brand_optimization",
}
```

#### Doctrine Loading
```python
class DoctrineLoader:
    def load_doctrine(
        self,
        doctrine_id: str,        # e.g., "prompts/instagram_copy"
        version: str,            # e.g., "v1.0.0"
        filename: str = "template.md"
    ) -> Tuple[str, DoctrineReference]:
        """Load doctrine file, verify path safety, compute hash."""
        # Whitelist check
        if doctrine_id not in ALLOWED_DOCTRINE_IDS:
            raise ValueError(f"Unsupported doctrine_id: {doctrine_id}")
        
        # Path safety: prevent path traversal
        if "/" in doctrine_id or ".." in doctrine_id:
            raise ValueError(f"Unsafe doctrine_id: {doctrine_id}")
        
        # Resolve file
        possible_paths = [
            repo_root / doctrine_id / version / filename,
            repo_root / "sigilzero" / doctrine_id / version / filename,
            repo_root / "app" / "sigilzero" / doctrine_id / version / filename,
            ...
        ]
        
        for path in possible_paths:
            if path.exists():
                content = path.read_bytes().decode("utf-8")
                ref = DoctrineReference(
                    doctrine_id=doctrine_id,
                    version=version,
                    sha256=sha256_bytes(content.encode("utf-8")),
                    resolved_path=path.relative_to(repo_root).as_posix(),
                )
                return content, ref
        
        raise FileNotFoundError(...)
```

#### Doctrine Snapshot
```json
{
  "doctrine_id": "prompts/instagram_copy",
  "version": "v1.0.0",
  "sha256": "sha256:...",
  "resolved_path": "sigilzero/prompts/instagram_copy/v1.0.0/template.md"
}
```

#### Manifest Doctrine Reference
```python
manifest.doctrine = DoctrineReference(
    doctrine_id=doctrine_ref.doctrine_id,
    version=doctrine_ref.version,
    sha256=doctrine_ref.sha256,
    resolved_path=doctrine_ref.resolved_path,  # Debug info only
)
```

#### No Timestamps in Doctrine
Field `resolved_at` is explicitly excluded from serialization:
```python
class DoctrineReference(BaseModel):
    doctrine_id: str
    version: str
    sha256: str
    resolved_at: str | None = Field(default=None, exclude=True)  # Not serialized
```

---

## Invariant 5: Filesystem Authoritative

### Requirement
Filesystem artifacts + manifest are source of truth. Postgres is index-only. System must function without DB.

### Implementation

#### Artifact Directory as Canonical Record
```
artifacts/
├── <job_id>/           # By governance job_id
│   ├── <run_id>/       # Deterministic run directory
│   │   ├── inputs/
│   │   ├── outputs/
│   │   └── manifest.json
│   ├── <run_id-2>/
│   └── .tmp/           # Temporary directory for atomic creation
├── runs/               # Legacy symlink compatibility
│   └── <run_id> → ../<job_id>/<run_id>
└── _write_test         # Disk writability test marker
```

#### Manifest: Authoritative Metadata
```json
{
  "schema_version": "1.2.0",
  "job_id": "ig-test-001",      // governance identifier
  "run_id": "d79bbc34291a40a4b0f6faa67e10fc2a",
  "queue_job_id": "rq-job-uuid", // ephemeral
  "job_ref": "jobs/ig-test-001/brief.yaml",
  "job_type": "instagram_copy",
  "started_at": "2026-02-28T...",  // excluded from determinism hash
  "finished_at": "...",           // excluded from determinism hash
  "status": "succeeded",
  "inputs_hash": "sha256:...",    // Deterministic
  "input_snapshots": {            // Snapshot metadata
    "brief": {
      "path": "inputs/brief.resolved.json",
      "sha256": "sha256:...",
      "bytes": 512
    },
    ...
  },
  "doctrine": {                   // Doctrine reference
    "doctrine_id": "prompts/instagram_copy",
    "version": "v1.0.0",
    "sha256": "sha256:..."
  },
  "artifacts": {                  // Output metadata
    "instagram_copy": {
      "path": "outputs/instagram_copy.md",
      "sha256": "sha256:..."
    }
  },
  "chain_metadata": {             // (Chainable only)
    "is_chainable_stage": true,
    "prior_stages": [
      {
        "run_id": "...",
        "job_id": "...",
        "stage": "brand_compliance_score",
        "output_references": ["artifacts/.../compliance_scores.json"]
      }
    ]
  }
}
```

#### Database: Index-Only
Postgres stores:
- Manifest references (job_id, run_id, timestamp) 
- Index pointers to filesystem artifacts
- Search metadata for UX

Database queries like:
```sql
SELECT job_id, run_id, status FROM runs WHERE job_id='ig-test-001' ORDER BY started_at DESC
```

But source of truth for execution data:
```python
manifest = json.load(artifacts/<job_id>/<run_id>/manifest.json)
```

#### Reindex Capability
System can rebuild DB from filesystem artifacts:
```bash
python scripts/reindex_artifacts.py /app
```

This rescans all `artifacts/**/manifest.json`, rebuilds database indices without loss of information.

---

## Invariant 6: No Silent Drift

### Requirement
Any change to inputs MUST change inputs_hash. Any change to inputs_hash MUST change run_id.

### Implementation

#### Change Propagation

**Scenario 1: Brief updated**
```yaml
# OLD
job_id: ig-test-001
tone_tags: ["authentic"]

# NEW
job_id: ig-test-001
tone_tags: ["authentic", "innovative"]
```

Steps:
1. Load new brief → model_dump → write `brief.resolved.json`
2. Hash file: `sha256:new_hash` ≠ `sha256:old_hash`
3. Compute inputs_hash from {brief: new_hash, ...}
4. Derive run_id from inputs_hash
5. New run_id ≠ old run_id → New artifact directory ✓

**Scenario 2: Context corpus updated**
1. Context loader scans corpus → retrieves different files
2. Concatenate & hash: `sha256:new_content_hash` ≠ before
3. Compute inputs_hash
4. Derive new run_id
5. Creates new artifact (can't silently mask drift) ✓

**Scenario 3: Model config updated**
1. ENV vars changed (LLM_MODEL, LLM_TEMPERATURE)
2. model_config.json updated & hashed
3. inputs_hash changes → run_id changes ✓

**Scenario 4: Doctrine version updated**
1. Brief specifies different doctrine version or loader finds new version
2. Doctrine file content different → hash changes
3. inputs_hash participates in inputs_hash → run_id changes ✓

**Scenario 5: Chainable: Prior artifact changed** (Critical for chains)
1. Prior stage rerun with different inputs
2. Prior run_id changes (different artifact)
3. Chainable stage loads prior_artifact snapshot
4. prior_artifact snapshot hash changes
5. inputs_hash includes prior_artifact hash
6. inputs_hash changes → run_id changes
7. No silent drift in chains ✓

### Verification
`DeterminismVerifier.verify_run_determinism()` in `sigilzero/core/determinism.py`:
- Reconstructs inputs_hash from snapshots
- Compares to recorded value
- Reconstructs run_id from inputs_hash
- Checks governance job_id matches brief

---

## Invariant 7: Backward Compatibility

### Requirement
POST /jobs/run API contract unchanged. Existing artifacts valid. Legacy symlinks work.

### Implementation

#### API Contract
Endpoint: `POST /jobs/run`

Request:
```json
{
  "job_ref": "jobs/ig-test-001/brief.yaml",
  "params": { ... }
}
```

Response (unchanged):
```json
{
  "job_id": "ig-test-001",
  "run_id": null
}
```

#### Artifact Structure Compatibility
Existing `artifacts/<job_id>/<run_id>/` directories remain valid:
- Old manifests (schema_version < 1.2.0) are still readable
- New manifests include `chain_metadata` but existing clients ignore unknown fields
- Snapshot files are additive (no breaking changes to old fields)

#### Legacy Symlink Compatibility
```python
def _ensure_legacy_symlink(run_id: str, canonical_dir: Path) -> str:
    """Create symlink for backward compatibility.
    
    artifacts/runs/<run_id> → ../<job_id>/<run_id>
    """
    legacy_link = Path("/app/artifacts/runs") / run_id
    relative_target = Path("..") / canonical_dir.parent.name / canonical_dir.name
    legacy_link.symlink_to(relative_target)
```

Old code that queries `artifacts/runs/<run_id>/` still works via symlink.

#### Excluded Fields for Backward Compatibility

In brief.resolved.json, exclude Stage 5 & 6 fields only if:
- NOT explicitly set in source brief
- AND at default values

```python
exclude_fields = set()

# Stage 5: Exclude generation mode fields only if not set AND at defaults
if ("generation_mode" not in brief_data and 
    brief.generation_mode == "single" and 
    brief.caption_variants == 1 and 
    brief.output_formats == ["md"]):
    exclude_fields.update({"generation_mode", "caption_variants", "output_formats"})

# Stage 6: Exclude retrieval fields only if not set AND in glob mode
if ("context_mode" not in brief_data and 
    brief.context_mode == "glob"):
    exclude_fields.update({"context_mode", "context_query", "retrieval_top_k", "retrieval_method"})

brief_resolved = brief.model_dump(exclude=exclude_fields)
```

This ensures:
- Old briefs (pre-Stage-5/6) produce same snapshots as before
- New briefs with explicit defaults preserve intent
- No silent changes to existing run_ids

---

## Testing & Verification

### Determinism Smoke Tests

**Test 1: Identical Inputs → Same run_id**
```python
def test_same_inputs_same_run_id():
    # Run job twice with identical inputs
    manifest1 = execute_job(repo_root, "jobs/ig-test-001/brief.yaml", params={})
    manifest2 = execute_job(repo_root, "jobs/ig-test-001/brief.yaml", params={})
    
    assert manifest1["run_id"] == manifest2["run_id"]
    assert manifest1["inputs_hash"] == manifest2["inputs_hash"]
    assert manifest1["status"] == "idempotent_replay" or manifest1 is manifest2
```

**Test 2: Different Inputs → Different run_id**
```python
def test_different_inputs_different_run_id():
    # Modify brief slightly
    brief_v1 = {"job_id": "test", "tone_tags": ["authentic"]}
    brief_v2 = {"job_id": "test", "tone_tags": ["authentic", "innovative"]}
    
    manifest1 = execute_job(repo_root, brief_v1)
    manifest2 = execute_job(repo_root, brief_v2)
    
    assert manifest1["run_id"] != manifest2["run_id"]
    assert manifest1["inputs_hash"] != manifest2["inputs_hash"]
```

**Test 3: Snapshot Files Present**
```python
def test_snapshots_present():
    manifest = execute_job(...)
    run_dir = Path(repo_root) / "artifacts" / manifest["job_id"] / manifest["run_id"]
    
    for snapshot_file in ["brief.resolved.json", "context.resolved.json", "model_config.json", "doctrine.resolved.json"]:
        assert (run_dir / "inputs" / snapshot_file).exists()
```

**Test 4: Snapshot Hashes Match**
```python
def test_snapshot_hashes():
    manifest = execute_job(...)
    valid, details = DeterminismVerifier.verify_run_determinism(run_dir)
    
    assert valid
    for check in details["checks"].values():
        assert check["valid"]
```

**Test 5: Run Replayable**
```python
def test_run_replayable():
    manifest = execute_job(...)
    run_dir = Path(repo_root) / "artifacts" / manifest["job_id"] / manifest["run_id"]
    
    can_replay, details = replay_run_idempotent(run_dir)
    assert can_replay
    assert not details["errors"]
```

**Test 6: Chainable - Prior Changes → Run Changes**
```python
def test_chain_no_silent_drift():
    # Prior stage run with inputs A
    prior_manifest = execute_brand_optimiation(prior_inputs_A)
    prior_run_id = prior_manifest["run_id"]
    
    # Chainable stage consumes prior
    chain_manifest_1 = execute_chainable_stage(prior_run_id=prior_run_id)
    chain_inputs_hash_1 = chain_manifest_1["inputs_hash"]
    
    # Prior stage run with inputs B (different)
    prior_manifest_2 = execute_brand_compliance(prior_inputs_B)
    prior_run_id_2 = prior_manifest_2["run_id"]
    
    # Chainable stage consumes different prior
    chain_manifest_2 = execute_chainable_stage(prior_run_id=prior_run_id_2)
    chain_inputs_hash_2 = chain_manifest_2["inputs_hash"]
    
    # Different prior → different inputs_hash → different run_id
    assert prior_run_id_2 != prior_run_id
    assert chain_inputs_hash_2 != chain_inputs_hash_1
    assert chain_manifest_2["run_id"] != chain_manifest_1["run_id"]
```

### Running Tests
```bash
# All determinism tests
python -m pytest app/scripts/smoke_determinism.py -v

# Specific test class
python -m pytest app/scripts/smoke_determinism.py::TestDeterminismInvariants -v

# Single test
python -m pytest app/scripts/smoke_determinism.py::TestDeterminismInvariants::test_same_inputs_same_run_id -v
```

---

## Schema Versions & Migration

### RunManifest Schema Evolution

| Version | Change | Migration |
|---------|--------|-----------|
| 1.0.0   | Initial (Phase 0) | N/A |
| 1.1.0   | Add input_snapshots | Backfill from filesystem |
| 1.2.0   | Add chain_metadata (Phase 8) | Set is_chainable_stage=false for all v1.1.0 |

Old clients that read v1.2.0 manifests:
- Unknown fields like `chain_metadata` are ignored (Pydantic default)
- All required fields (job_id, run_id, status) remain unchanged
- Backward compatible ✓

---

## Operational Procedures

### Validate Existing Artifacts
```bash
python -c "
from pathlib import Path
from sigilzero.core.determinism import DeterminismVerifier

run_dir = Path('artifacts/ig-test-001/d79bbc34291a40a4b0f6faa67e10fc2a')
is_valid, details = DeterminismVerifier.verify_run_determinism(run_dir)
print(f'Valid: {is_valid}')
print(f'Details: {details}')
"
```

### Replay an Existing Run (with Same Outputs)
```bash
curl -X POST http://localhost:8000/jobs/run \
  -H "Content-Type: application/json" \
  -d '{"job_ref": "jobs/ig-test-001/brief.yaml", "params": {}}'
```

Returns same run_id if inputs unchanged (idempotent).

### Rebuild Database from Artifacts
```bash
python app/scripts/reindex_artifacts.py /app
```

Scans all manifest.json files, rebuilds Postgres indices without data loss.

---

## Summary: Definition of Done

✅ **Phase 1.0 Determinism Guardrails Complete**

- [x] Canonical input snapshots written to disk (brief, context, model_config, doctrine, prior_artifact)
- [x] Deterministic run_id derivation from inputs_hash only
- [x] Governance job_id from brief (queue_job_id separate)
- [x] Doctrine versioned, hashed, participating in inputs_hash
- [x] Filesystem authoritative (DB index-only)
- [x] No silent drift (input changes → run_id changes)
- [x] Backward compatible API + artifact structures
- [x] Snapshot validation utilities
- [x] Determinism verification module
- [x] Smoke tests for all invariants
- [x] Comprehensive architecture documentation
"""
