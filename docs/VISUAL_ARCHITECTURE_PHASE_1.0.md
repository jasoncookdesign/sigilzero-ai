# PHASE 1.0 DETERMINISM GUARDRAILS - VISUAL ARCHITECTURE

## Determinism Chain: Input → Hash → run_id

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PHASE 1.0 EXECUTION MODEL                     │
└─────────────────────────────────────────────────────────────────────┘

INPUT SOURCES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────┐  ┌────────────────┐  ┌──────────────┐
  │  brief.yaml  │  │  corpus/*.md   │  │  env  vars   │
  │ (governance) │  │  (context)     │  │  (config)    │
  └──────┬───────┘  └────────┬───────┘  └──────┬───────┘
         │                   │                  │
         └───────────────┬───────────────┬──────┘
                         │               │
                    (read & snapshot to disk)
                         │               │
         ┌───────────────┴───────────────┴──────────────────────┐
         │                                                       │
         │      CANONICAL INPUT SNAPSHOTS (JSON)               │
         │      artifacts/<job_id>/<run_id>/inputs/            │
         │                                                       │
         │  ├── brief.resolved.json ───────┐                   │
         │  │  {job_id, brand, tone_tags} │                   │
         │  │  (governance snapshot)       │                   │
         │  │                              │                   │
         │  ├── context.resolved.json ─────┤                   │
         │  │  {spec, content, hash}      │                   │
         │  │  (corpus + retrieval config) │                   │
         │  │                              │                   │
         │  ├── model_config.json ────────┤                   │
         │  │  {provider, model, temp}    │                   │
         │  │  (LLM configuration)         │                   │
         │  │                              │                   │
         │  ├── doctrine.resolved.json ───┤                   │
         │  │  {doctrine_id, version,     │                   │
         │  │   sha256, resolved_path}    │                   │
         │  │  (versioned template)        │                   │
         │  │                              │                   │
         │  └── prior_artifact.resolved.json  (chainable only) │
         │     {prior_run_id, output_hashes} (no silent drift) │
         │                                                       │
         └───────────────┬───────────────────────────────────┬──┘
                         │                                   │
                         ↓ (Phase 1.0 INVARIANT 1)          ↓
                  (All inputs snapshotted)         (Hashes from file bytes)
                         │                                   │
HASHING LAYER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                    ┌────────────────────────────────────┐
                    │   Hash Each Snapshot File (bytes)  │
                    │   sha256:<file_bytes>              │
                    └────────────────┬───────────────────┘
                                     │
                                     ↓
         ┌───────────────────────────────────────────────┐
         │  SNAPSHOT HASHES (alphabetically sorted)      │
         │                                               │
         │  {                                            │
         │    "brief": "sha256:abc123...",              │
         │    "context": "sha256:def456...",            │
         │    "doctrine": "sha256:ghi789...",           │
         │    "model_config": "sha256:jkl012...",       │
         │    "prior_artifact": "sha256:mno345..."      │
         │  }                                            │
         │                                               │
         │  (Phase 1.0 INVARIANT 2: Derived from hashes)│
         └──────────────┬────────────────────────────────┘
                        │
                        ↓ compute_inputs_hash()
                        │ (canonical_json + sort keys)

DETERMINISM COMPUTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

         ┌──────────────────────────────────────────────┐
         │        inputs_hash                           │
         │        = sha256(canonical_json(snapshot_hash │
         │                   dict_sorted))              │
         │                                              │
         │        "sha256:xyz789abc123def456ghi..."    │
         │                                              │
         │  (Phase 1.0 INVARIANT 1+2: Combined hash)   │
         └──────────────┬───────────────────────────────┘
                        │
                        ↓ derive_run_id()
                        │ (first 32 hex chars)

         ┌──────────────────────────────────────────────┐
         │        run_id                                │
         │        = inputs_hash[:32]                    │
         │                                              │
         │        "d79bbc34291a40a4b0f6faa67e10fc2a"   │
         │                                              │
         │  (Phase 1.0 INVARIANT 2: Deterministic)     │
         │  (No randomness, no timestamps)             │
         └──────────────┬───────────────────────────────┘
                        │

ARTIFACT DIRECTORY CREATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                        │
                        ↓
         ┌──────────────────────────────────────────────┐
         │  artifacts/<job_id>/<run_id>/                │
         │  ├── inputs/                                 │
         │  │   ├── brief.resolved.json                │
         │  │   ├── context.resolved.json              │
         │  │   ├── model_config.json                  │
         │  │   ├── doctrine.resolved.json             │
         │  │   └── prior_artifact.resolved.json       │
         │  │                                           │
         │  ├── outputs/                                │
         │  │   ├── instagram_copy.md                  │
         │  │   └── ...                                │
         │  │                                           │
         │  └── manifest.json ◄─────┐                 │
         │     {                     │                 │
         │      job_id,              │                 │
         │      run_id,              │                 │
         │      inputs_hash,         │                 │
         │      input_snapshots,     │                 │
         │      doctrine,            │                 │
         │      artifacts,           │                 │
         │      chain_metadata       │                 │
         │     }                     │                 │
         │  (Canonical manifest)    │                 │
         │                           │                 │
         │  (Phase 1.0 INVARIANTS:)  │                 │
         │    1. Snapshots present   │                 │
         │    3. job_id from brief   │                 │
         │    4. Doctrine recorded   │                 │
         │    5. Filesystem source   │                 │
         │    7. Schema v1.2.0       │                 │
         └──────────────────────────┴─────────────────┘

IDEMPOTENT REPLAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Run 1: compute inputs_hash → run_id="d79bbc34..." → Create artifacts/
  Run 2: compute inputs_hash → run_id="d79bbc34..." ┐
                                                      │ SAME RUN_ID
                                                      → return to existing dir
  Run 3: Modified brief → inputs_hash ≠              │
                                                      → run_id="d88d41f7..."
                                                      → new directory

  (Phase 1.0 INVARIANT 6: No Silent Drift)
  Input change → inputs_hash change → run_id change

DATABASE ROLE (Index-Only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────────────────────────────┐
  │  Filesystem (AUTHORITATIVE)                       │
  │  artifacts/<job_id>/<run_id>/manifest.json        │
  │  ► Source of truth                                 │
  │  ► Survives DB failures                           │
  │  ► Reindex capability                             │
  └────────────────────────────────────────────────────┘
                        │
                        │ (index)
                        ↓
  ┌────────────────────────────────────────────────────┐
  │  Database (Secondary Index)                       │
  │  runs table: job_id, run_id, status, timestamp    │
  │  ► Performance optimization                       │
  │  ► Search capability                              │
  │  ► Monitoring (not authoritative)                │
  │  ► Rebuildable with:                              │
  │    python scripts/reindex_artifacts.py            │
  └────────────────────────────────────────────────────┘

  (Phase 1.0 INVARIANT 5: Filesystem Authoritative)
```

## No Silent Drift Example

```
SCENARIO: Context corpus updated

BEFORE:
  Brief: {job_id: "ig-test-001", brand: "SIGIL.ZERO"}
  Context: Load identity/*, strategy/* → "content hash V1"
  Snapshots:
    ├── brief → "sha256:ABC"
    └── context → "sha256:DEF"
  inputs_hash = sha256({brief: ABC, context: DEF}) = "sha256:GHI"
  run_id = "ghiabc..."
  artifacts/ig-test-001/ghiabc.../manifest.json

CORPUS CHANGES (new files added to corpus/)

AFTER (same brief):
  Brief: {job_id: "ig-test-001", brand: "SIGIL.ZERO"} (unchanged)
  Context: Load identity/*, strategy/*, NEW FILE/* → "content hash V2" (different!)
  Snapshots:
    ├── brief → "sha256:ABC" (same)
    └── context → "sha256:XXX" (DIFFERENT)
  inputs_hash = sha256({brief: ABC, context: XXX}) = "sha256:JKL" (DIFFERENT!)
  run_id = "jkldef..." (DIFFERENT!)
  artifacts/ig-test-001/jkldef.../manifest.json (NEW DIRECTORY!)

RESULT:
  ✓ NO SILENT DRIFT
  ✓ Drift detected through run_id change
  ✓ Old and new artifacts coexist
  ✓ Complete audit trail

(Phase 1.0 INVARIANT 6: No Silent Drift)
```

## Chainable Pipelines: Prior Artifact Changes

```
STAGE 7: Brand Compliance Scoring
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Input:  Brief with compliance thresholds
Output: compliance_scores.json
Result: artifacts/brand-score-001/<run_id_A>/
  manifest.json: {run_id: "abc123...", outputs: {compliance_scores.json}}

STAGE 8: Brand Optimization (Chainable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Input:  Brief with chain_inputs.prior_run_id = "abc123..."
        ├── Loads prior artifact from filesystem
        └── Creates prior_artifact.resolved.json snapshot with:
               {
                 prior_run_id: "abc123...",
                 prior_output_hashes: {
                   "compliance_scores.json": "sha256:OLD_HASH"
                 }
               }

Snapshot Hashes:
  {
    brief: ...,
    context: ...,
    model_config: ...,
    doctrine: ...,
    prior_artifact: "sha256:<hash_of_prior_snapshot>"  ◄─── INCLUDES PRIOR
  }

inputs_hash = compute(snapshot_hashes)

run_id = derive(inputs_hash)

SCENARIO: Prior stage rerun with different inputs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Stage 7 rerun:
  Different input → different inputs_hash → NEW run_id = "abc456..."
  artifacts/brand-score-001/abc456.../
    outputs/compliance_scores.json  (different content))

Stage 8 attempts same chain (prior_run_id = "abc123...", unchanged brief):
  Prior artifact snapshot: {prior_run_id: "abc123...", ...}  (unchanged)
  BUT: Loads from artifacts/brand-score-001/abc123.../
  ASSERT: Expected prior_output_hashes don't match!
  RESULT: ERROR or RERUN with new prior_run_id = "abc456..."

WHEN: Brief updated with prior_run_id = "abc456...":
  Prior artifact snapshot: {prior_run_id: "abc456...", ...}  (DIFFERENT)
  prior_artifact snapshot_hash CHANGES
  inputs_hash CHANGES
  run_id CHANGES to "xyz789..."
  New directory: artifacts/optimization-001/xyz789.../

RESULT:
  ✓ NO SILENT DRIFT IN CHAINS
  ✓ Prior changes propagate to downstream
  ✓ Complete audit trail
  ✓ Chain integrity maintained

(Phase 1.0 INVARIANT 6: No Silent Drift)
(Enabled by INVARIANT 1: prior_artifact snapshot)
```

## Backward Compatibility

```
PHASE 0 (Pre-Phase 1.0)          PHASE 1.0 (Current)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

API:
POST /jobs/run                    POST /jobs/run
{job_ref, params}        →        {job_ref, params}  (SAME)
→ {job_id, run_id: null}         → {job_id, run_id: null}  (SAME)

Artifact Structure:
artifacts/ig-test-001/             artifacts/ig-test-001/
└── d79bbc34.../                   └── d79bbc34.../
    ├── manifest.json                   ├── inputs/  (NEW)
    └── outputs/                        │   ├── brief.resolved.json
                                        │   ├── context.resolved.json
                                        │   ├── model_config.json
                                        │   └── doctrine.resolved.json
                                        ├── manifest.json  (ENHANCED: v1.2)
                                        └── outputs/

Manifest Schema:
v1.0.0                           v1.2.0
{                                {
  job_id,                          job_id,
  run_id,                          run_id,
  status,                          status,
  ...                              input_snapshots,  (NEW)
}                                doctrine,         (NEW)
                                 chain_metadata,   (NEW)
                               }

Brief Snapshot (brief.resolved.json):
Phase 0 Brief:                   Phase 0 Brief:
{                                {
  job_id,                          job_id,
  job_type,                        job_type,
  brand,                           brand,
  ...                              ...
  // no generation_mode            // EXCLUDED: generation_mode (no default)
  // no context_mode               // EXCLUDED: context_mode (no default)
}                                }
                                 HASH: Same! ✓

Phase 5 Brief:                   Phase 5 Brief:
{                                {
  ...,                             ...,
  generation_mode: "variants",     generation_mode: "variants",  (INCLUDE:
  caption_variants: 3,             caption_variants: 3,          explicit)
  ...                              ...
}                                }
                                 HASH: Same! ✓

RESULT:
✓ All existing artifacts remain valid
✓ Existing APIs work unchanged
✓ Old briefs produce same snapshots (no breaking changes)
✓ New briefs can use Phase 5/8 features without changing run_ids
✓ Schema evolution is non-breaking (new fields optional)

(Phase 1.0 INVARIANT 7: Backward Compatibility)
```

---

This visual architecture confirms all 7 Phase 1.0 Determinism Invariants are implemented and enforced at every level of the system.
