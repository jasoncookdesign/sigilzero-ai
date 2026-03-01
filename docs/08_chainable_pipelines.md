# Stage 8: Chainable Pipelines

## Objective
Enable sequential composition of pipelines while preserving all Phase 1.0 determinism invariants. A chainable pipeline:
- Takes output from a prior stage (e.g., Stage 7: brand_compliance_score)
- Processes it through one or more additional stages
- Produces a single final artifact with complete audit trail
- Maintains canonical snapshot-based determinism throughout

## Feature Specification

### Chainable Pipeline Contract
1. **Input Reference**: Pipeline receives `prior_run_id` in brief
2. **Prior Artifact Loading**: Previous artifact (output + manifest) loaded from filesystem
3. **Input Composition**: Current inputs + prior manifest data → new inputs_hash
4. **Chain Tracking**: Intermediate run_ids recorded in final manifest chain log
5. **Output Aggregation**: All stage outputs available in final artifacts

### Example: Brand Compliance → Content Optimization Chain
```yaml
# Stage 8: brand_optimization (chainable after brand_compliance_score)
stage: brand_optimization
job_id: optimization-001
prior_stage: brand_compliance_score
chain_inputs:
  prior_run_id:  "faa5aa5e64e7454d9d789a455e59a63f"  # From Stage 7
  compliance_scores_path: "artifacts/brand-score-001/faa5aa5e64e.../outputs/compliance_scores.json"
```

### Phase 1.0 Invariants (ALL ENFORCED)

#### 1. Canonical Input Snapshots
- Stage 8 writes new snapshot: `inputs/prior_artifact.json` (previous stage's manifest + outputs metadata)
- All inputs frozen as JSON before processing
- Stable JSON ordering (sorted keys)

#### 2. Deterministic run_id
- run_id derived from inputs_hash
- inputs_hash includes: brief, context, model_config, doctrine, **prior_artifact**
- Same prior_run_id + same new inputs → same run_id

#### 3. Governance-Level job_id
- job_id from brief.yaml (governance)
- prior_run_id is data input, not governance identifier
- Queue job UUID recorded separately

#### 4. Doctrine as Hashed Input
- Stage 8 doctrine (if used) versioned and hashed
- Doctrine hash participates in inputs_hash
- Version + hash recorded in manifest

#### 5. Filesystem Authoritative
- `artifacts/<job_id>/<run_id>/` contains complete job state
- manifest.json lists all inputs + outputs (including prior artifact reference)
- Postgres is cache only
- System must function without DB

#### 6. No Silent Drift
- Change prior_run_id → inputs_hash changes → run_id changes
- Change Stage 8 processing logic (doctrine) → run_id changes
- Smoke test verifies: same prior_run_id + same inputs → same run_id

#### 7. Backward Compatibility
- POST /jobs/run API unchanged
- job_ref semantics unchanged
- Stage 1, 5, 6, 7 artifacts remain valid
- Non-chainable pipelines (traditional) unaffected

---

## Implementation Plan

### Phase 8a: Pipeline Registry Enhancement
- Add `chainable: bool` field to pipeline registry
- Add `accepts_prior_run_id: bool` flag
- Define `ChainInput` schema (prior_run_id, required_outputs)

### Phase 8b: Brief Schema Extension
```python
class ChainableJobBrief(JobBrief):
    """Extended brief supporting chainable pipelines."""
    stage: str  # e.g., "brand_optimization"
    chainable: bool = False
    chain_inputs: Optional[ChainInput] = None  # If None, stage is standalone
    
class ChainInput(BaseModel):
    prior_run_id: str  # UUID from prior stage
    prior_stage: str  # e.g., "brand_compliance_score"
    required_outputs: List[str] = []  # e.g., ["compliance_scores.json"]
```

### Phase 8c: Snapshot Extension
- New snapshot type: `prior_artifact.resolved.json`
- Contains: prior manifest (metadata only, not full output) + output references
- Hashed and included in inputs_hash computation

### Phase 8d: Pipeline Implementation
1. Load prior artifact from filesystem
2. Validate prior_run_id signature + outputs exist
3. Create `prior_artifact.json` snapshot
4. Compute inputs_hash (including prior_artifact hash)
5. Derive run_id from inputs_hash
6. Execute stage (using prior outputs as context)
7. Write all snapshots atomically
8. Record chain in manifest

### Phase 8e: Manifest Chain Tracking
```json
{
  "chain_metadata": {
    "is_chainable_stage": true,
    "prior_stages": [
      {
        "run_id": "faa5aa5e64e7...",
        "job_id": "brand-score-001",
        "stage": "brand_compliance_score",
        "output_references": [
          "artifacts/brand-score-001/faa.../outputs/compliance_scores.json"
        ]
      }
    ]
  }
}
```

---

## Determinism Validation

### Test: Chain Determinism
```python
def test_chain_determinism():
    # Run 1: prior_run_id X + new inputs Y → run_id Z
    result1 = run_chainable_pipeline(prior_run_id="faa...", inputs=Y)
    
    # Run 2: same prior_run_id X + same inputs Y → MUST be run_id Z
    result2 = run_chainable_pipeline(prior_run_id="faa...", inputs=Y)
    
    assert result1.run_id == result2.run_id
    assert result1.manifest_bytes == result2.manifest_bytes  # Byte-perfect determinism
```

### Test: Prior Run_id Change Breaks Chain
```python
def test_chain_prior_change_changes_run_id():
    # Run 1: prior_run_id X
    result1 = run_chainable_pipeline(prior_run_id="faa...", inputs=Y)
    
    # Run 2: different prior_run_id W (different prior artifact)
    result2 = run_chainable_pipeline(prior_run_id="abc...", inputs=Y)
    
    assert result1.run_id != result2.run_id  # Must be different!
```

---

## Governance Alignment

- job_id from brief (governance)
- prior_run_id is DATA INPUT (participates in inputs_hash)
- Stage routing via registry (no dynamic decisions)
- Doctrine versioned and hashed

---

## Backward Compatibility

- Existing pipelines (instagram_copy, retrieval, brand_compliance_score) remain unchanged
- Non-chainable pipelines function as Stage 1-7
- POST /jobs/run API contract preserved
- Legacy artifact structure valid
- Orphaned symlink detection operational

---

## Definition of Done

- [ ] Pipeline registry supports `chainable` flag
- [ ] ChainInput schema defined and validated
- [ ] Prior artifact snapshot created and hashed
- [ ] inputs_hash includes prior_artifact hash
- [ ] Chain metadata recorded in manifest
- [ ] Chainable determinism test: 2/2 passing
- [ ] Prior run_id change test: passed
- [ ] reindex --verify passes on chained artifacts
- [ ] Non-chainable pipelines unaffected (Stage 1-7 tests pass)
- [ ] Backward compatibility manifest structure valid

---

## Architect Reporting Block (REQUIRED AFTER IMPLEMENTATION)

**Will provide:**
1. ✅ Structural changes summary
   - Registry enhancements
   - Brief schema extension
   - Snapshot types added
   - Manifest chain tracking structure

2. ✅ Determinism validation
   - inputs_hash includes prior_artifact hash
   - run_id derived deterministically from inputs_hash
   - Smoke tests: chain_determinism (2/2), run_id_change (1/1)
   - Manifest byte-perfect determinism confirmed

3. ✅ Governance alignment
   - job_id from brief (governance)
   - prior_run_id treated as data input
   - Doctrine versioning preserved
   - Registry-based routing enforced

4. ✅ Backward compatibility confirmation
   - Stage 1-7 tests: all passing
   - Post /jobs/run API unchanged
   - Legacy artifacts remain valid
   - Non-chainable pipelines unaffected

5. ✅ Filesystem authority confirmation
   - Canonical snapshots: inputs/prior_artifact.resolved.json
   - Manifest lists all inputs + outputs + chain references
   - Artifact directory contains complete job state
   - Reindex --verify passes (filesystem authoritative)
