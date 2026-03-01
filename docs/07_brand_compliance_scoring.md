# Stage 7: Brand Compliance Scoring

## Objective
Implement deterministic brand compliance scoring that evaluates content against brand identity and strategy guidelines. This stage extends the pipeline architecture to support multi-input scoring workflows while preserving snapshot-based determinism.

## Feature Overview
Given brand identity (corpus), strategy guidance, and content to evaluate, the system produces:
- **Compliance Scores** (0-100) across multiple dimensions
- **Evaluation Details** with specific guidance alignment analysis
- **Improvement Recommendations** tied to governance documents

## Architectural Invariants (Enforced)

### 1. Canonical Input Snapshots
All inputs written to disk at:
```
artifacts/<job_id>/<run_id>/inputs/
├── brief.resolved.json          (governance: scoring request + config)
├── context.resolved.json        (content to evaluate + brand identity)
├── model_config.json           (LLM + scoring parameters)
└── doctrine.resolved.json      (brand governance + strategy)
```

**Mechanism:**
- Brief specifies job_type, content boundaries (min/max compliance)
- Context contains: brand identity (from corpus), content to score, evaluation focus
- Model config defines: model, temperature, max_tokens for determinism
- Doctrine: v1.0.0 brand positioning, strategy, compliance framework

### 2. Deterministic run_id
```
inputs_hash = sha256(
    hash(brief.resolved.json) +
    hash(context.resolved.json) +
    hash(model_config.json) +
    hash(doctrine.resolved.json)
)
run_id = first_32_chars(inputs_hash)
```

**Guarantee:** Same brief + context + doctrine → same run_id (deterministic)

### 3. Governance-Level job_id
```yaml
# jobs/brand-score-001/brief.yaml
job_id: brand-score-001          # Governance identifier (from brief)
job_type: brand_compliance_score # Registry-routed
content:
  title: "Sample Campaign"
  body: "Marketing content..."
  channels: ["instagram", "tiktok"]
brand_identity_scope: "brand_voice+positioning"
evaluation_focus: "authenticity,alignment_with_values"
```

**Invariant:** job_id from brief YAML (user governance), not generated.

### 4. Doctrine as Hashed Input
Brand governance doctrine (v1.0.0):
```
corpus/identity/Brand_Voice.md
corpus/strategy/Marketing_Principles.md
corpus/strategy/Positioning.md
```

**Mechanism:**
- Load versioned doctrine from repo: `doctrine.doctrine_id/version/sha256`
- Compute doctrine content hash
- Include doctrine hash in inputs_hash
- Record in manifest: `manifest.doctrine = {doctrine_id, version, sha256}`

**Invariant:** Doctrine changes → inputs_hash changes → run_id changes

### 5. Filesystem Authoritative
```
artifacts/brand-score-001/
  a1b2c3d4e5f6.../
    ├── manifest.json
    ├── inputs/
    │   ├── brief.resolved.json (governance request)
    │   ├── context.resolved.json (content + brand identity)
    │   ├── model_config.json (LLM config)
    │   └── doctrine.resolved.json (brand strategy snapshot)
    └── outputs/
        └── compliance_scores.json (model output)
```

**Authority Chain:**
1. Filesystem artifacts are source of truth
2. Manifest.json records snapshot hashes + metadata
3. PostgreSQL is index-only (rebuildable via reindex)
4. No data lives in DB that cannot be reconstructed from artifacts

### 6. No Silent Drift
**Smoke Tests Verify:**
- Same inputs → same run_id (determinism)
- Changed brief (e.g., different content) → different run_id
- Changed doctrine → different run_id
- Manifest byte identity across clean re-runs
- Legacy symlink consistency

### 7. Backward Compatibility
**API Contract:**
- `POST /jobs/run` accepts new `job_type: brand_compliance_score`
- Job submission already supports arbitrary brief structure
- Manifest format unchanged (backward compatible snapshots)
- Existing instagram_copy runs unaffected

---

## Implementation Details

### Pipeline: `phase0_brand_compliance_score.py`
```python
def run_brand_compliance_score(
    brief: BrandComplianceBrief,
    repo_root: Path,
    job_id: str
) -> tuple[str, Path]:
    """
    1. Resolve inputs from brief + context + config
    2. Write canonical JSON snapshots to artifacts/<job_id>/<run_id>/inputs/
    3. Compute inputs_hash from snapshot hashes (deterministic)
    4. Derive run_id from inputs_hash
    5. Create/finalize manifest with snapshot metadata
    6. Call LLM for compliance scoring
    7. Write outputs to artifacts/<job_id>/<run_id>/outputs/
    8. Return (run_id, artifact_dir)
    """
```

**Key Operations:**
- `_write_snapshot()`: Write JSON to artifact path + compute hash
- `_compute_inputs_hash()`: Aggregate snapshot hashes deterministically
- `_derive_run_id()`: From inputs_hash (no randomness)
- `_create_manifest()`: Record job metadata + snapshot hashes
- `_score_compliance()`: LLM call (deterministic temperature=0)
- `_finalize_run()`: Write outputs, update manifest status

### Snapshots Structure

**brief.resolved.json** (governance spec):
```json
{
  "job_id": "brand-score-001",
  "job_type": "brand_compliance_score",
  "job_ref": "jobs/brand-score-001/brief.yaml",
  "content": {
    "title": "Sample Campaign",
    "body": "...",
    "channels": ["instagram"]
  },
  "brand_identity_scope": "brand_voice+positioning",
  "evaluation_focus": "authenticity,alignment_with_values",
  "config": {
    "min_score": 0,
    "max_score": 100,
    "dimensions": ["authenticity", "alignment", "clarity"]
  }
}
```

**context.resolved.json** (content + guidance):
```json
{
  "brand_identity": {
    "voice_principles": ["authentic", "direct", "innovative"],
    "positioning": "premium indie brand",
    "values": ["transparency", "quality"]
  },
  "content_to_score": {
    "title": "Sample Campaign",
    "body": "...",
    "channels": ["instagram"]
  },
  "evaluation_context": {
    "focus_areas": ["authenticity", "alignment_with_values", "clarity"],
    "scoring_rubric": "0=misaligned, 50=partial, 100=exemplary"
  }
}
```

**model_config.json** (determinism):
```json
{
  "model": "gpt-4",
  "temperature": 0,
  "max_tokens": 2000,
  "response_format": "json"
}
```

**doctrine.resolved.json** (strategy snapshot):
```json
{
  "doctrine_id": "brand_governance",
  "version": "v1.0.0",
  "sha256": "abc123...",
  "content": "Composite of Brand_Voice.md + Marketing_Principles.md + Positioning.md"
}
```

### Response Schema: `compliance_scores.json`
```json
{
  "run_id": "a1b2c3d4e5f6...",
  "job_id": "brand-score-001",
  "timestamp": "2026-02-28T...",
  "scores": {
    "authenticity": {
      "score": 92,
      "reasoning": "Voice aligns with transparency values"
    },
    "alignment_with_values": {
      "score": 88,
      "reasoning": "Content demonstrates quality commitment"
    },
    "clarity": {
      "score": 85,
      "reasoning": "Message structure clear, could tighten CTA"
    }
  },
  "overall_score": 88,
  "recommendations": [
    "Strengthen innovation positioning in opening",
    "Add explicit quality assurance reference"
  ],
  "guidance_alignment": {
    "brand_voice": "strong",
    "positioning": "good",
    "values_expression": "strong"
  }
}
```

---

## Definition of Done

- [ ] Snapshot-based inputs written to canonical paths
- [ ] JSON serialization uses stable ordering (sorted keys)
- [ ] inputs_hash computed deterministically from snapshots only
- [ ] run_id derived from inputs_hash (no randomness, no collisions)
- [ ] Manifest records snapshot paths, hashes, doctrine version
- [ ] Filesystem artifacts are authoritative (DB index-only)
- [ ] API backward compatible (POST /jobs/run with new job_type)
- [ ] Legacy symlinks created (artifacts/runs/<run_id>)
- [ ] Smoke tests pass (determinism validation)
- [ ] No silent drift (input changes propagate to run_id)

## Determinism Validation (Smoke Tests)

**test_compliance_scorer_determinism**
- Same brief + context → same run_id (idempotent)
- run_id derived correctly from inputs_hash
- Manifest consistent across runs

**test_compliance_content_change_changes_run_id**
- Different content to score → different run_id
- Proves inputs_hash captures content variance

**test_compliance_doctrine_change_changes_run_id**
- Different doctrine version → different run_id
- Proves governance versioning affects determinism

**test_compliance_backward_compatibility**
- Job ref unchanged (jobs/<job_id>/brief.yaml)
- Manifest structure compatible with reindex

---

## Governance Reporting

At completion, provide:
1. **Structural Changes**: Files created, snapshot layout, registry updates
2. **Determinism Validation**: Proof that all 7 invariants enforced
3. **Governance Alignment**: job_id from brief, doctrine versioned/hashed
4. **Backward Compatibility**: API contract preserved, existing jobs unaffected
5. **Filesystem Authority**: Verification that DB rebuilds from artifacts alone
