# Stage 5: Generation Modes Implementation

## Objective
Enable explicit, enumerated generation strategies (modes) while preserving all Phase 1.0 determinism guardrails:
- Snapshot-based canonical inputs
- Deterministic run_id derivation
- Governance-level job_id
- Filesystem-authoritative persistence
- Code-defined registry
- Versioned doctrine loading
- Backward-compatible API surface

## Implementation Summary

### Mode A: Single (Default)
- Generates exactly 1 output (current/legacy behavior)
- Outputs written as today: `outputs/instagram_captions.md`
- Fully backward compatible
- Used when `generation_mode: "single"` or omitted (defaults to "single")

### Mode B: Variants (Deterministic Multi-Generation)
- Generates N deterministic variations in same run directory
- N specified via `caption_variants: <int>` in brief (1-20)
- Output layout:
  - `outputs/instagram_captions.md` (primary variant for backward compatibility)
  - `outputs/variants/01.md`, `02.md`, ..., `NN.md` (individual variant files)
  - `outputs/variants/variants.json` (structured array of all variants)
- **Determinism mechanism**: Each variant uses seed derived from:
  ```
  seed_i = sha256(inputs_hash + ":variant:" + variant_index)
  ```
  Seeds are recorded in `manifest.generation_metadata.seeds` for reproducibility
- Mode selection: `generation_mode: "variants"` + `caption_variants: N`

### Mode C: Format (Output Format Flexibility)
- Controls output packaging without changing underlying content
- Always generates `outputs/instagram_captions.md` (mandatory for backward compatibility)
- Additionally generates selected formats:
  - `outputs/instagram_captions.json` (structured caption data)
  - `outputs/instagram_captions.yaml` (YAML-formatted captions)
- Mode selection: `generation_mode: "format"` + `output_formats: ["md", "json", "yaml"]`

## Code Changes

### 1. BriefSpec Schema Update (`app/sigilzero/core/schemas.py`)
Added three new fields to control generation:
```python
generation_mode: Literal["single", "variants", "format"] = Field(default="single")
caption_variants: int = Field(default=1, ge=1, le=20)  # For variants mode
output_formats: List[Literal["md", "json", "yaml"]] = Field(default_factory=lambda: ["md"])  # For format mode
```

### 2. RunManifest Schema Update (`app/sigilzero/core/schemas.py`)
Added metadata field to record generation strategy:
```python
generation_metadata: Dict[str, Any] = Field(default_factory=dict)
```

Populated with:
- `generation_mode: str` - the mode used
- `variant_count: int` - number of variants generated
- `seeds: Dict[int, str]` (variants mode only) - deterministic seeds used for each variant

### 3. Phase0 Pipeline Update (`app/sigilzero/pipelines/phase0_instagram_copy.py`)
Refactored generation logic to:
1. Extract caption parsing into reusable `_parse_captions()` helper
2. Generate variants in loop (1 for single/format, N for variants)
3. For variants mode: compute deterministic seeds from inputs_hash
4. Collect all variants into structured format
5. Write outputs based on mode:
   - Mode A/B: Always write `outputs/instagram_captions.md`
   - Mode B: Write individual variant files + `variants.json`
   - Mode C: Write JSON/YAML alongside markdown
6. Record all artifacts in manifest with content hashes

### 4. Makefile Update
Added test target:
```makefile
smoke_generation_modes:
	@echo "Running Stage 5 Generation Modes Smoke Tests..."
	docker exec sz_worker python /app/scripts/smoke_generation_modes.py
```

### 5. New Smoke Test Suite (`app/scripts/smoke_generation_modes.py`)
Four comprehensive tests:
1. **test_mode_a_single**: Verifies Mode A maintains backward compatibility and determinism
2. **test_mode_b_variants**: Verifies deterministic multi-generation with seeded randomness
3. **test_mode_c_format**: Verifies output format flexibility with valid JSON/YAML
4. **test_backward_compatibility**: Ensures default mode (A) is used when not specified

## Determinism Validation

### Invariant 1: Snapshot-Based Canonical Inputs
**Status**: ✅ PRESERVED
- All generation modes freeze `brief.resolved.json` with generation_mode and variant config
- `inputs_hash` computed from snapshot hashes only (includes brief snapshot)
- Mode selection is deterministic because it's in the brief snapshot
- Multiple runs with same brief snapshot → same inputs_hash → same run_id

### Invariant 2: Deterministic run_id Derivation
**Status**: ✅ PRESERVED
- `run_id = sha256(inputs_hash).hex()[:16]` remains unchanged
- Generation parameters (generation_mode, caption_variants, output_formats) are ALL in brief snapshot
- Changing any mode parameter changes brief snapshot → new inputs_hash → new run_id
- run_id is independent of generation strategy; same run_id always means identical inputs

### Invariant 3: Deterministic Variant Generation
**Status**: ✅ NEW GUARANTEE (Variants Mode Only)
- Each variant uses explicit seed: `seed = sha256(inputs_hash + ":variant:" + i).hex()[:8]`
- Seeds are deterministic function of inputs_hash only
- Same inputs → same seeds → same variant outputs (if model supports seeding)
- Seeds are recorded in manifest for auditability

### Invariant 4: No Silent Drift
**Status**: ✅ PRESERVED
- Any change to generation parameters changes brief snapshot
- Changed snippet → different inputs_hash → different run_id
- Impossible to silently change modes under same run_id
- Manifest explicitly records which mode was used

## Governance Alignment

### Governance Separation: job_id vs. queue_job_id
**Status**: ✅ PRESERVED
- `job_id` from brief (governance identifier) - unchanged
- `queue_job_id` from RQ runtime (ephemeral) - unchanged
- Generation mode parameters are part of brief schema, therefore part of governance input
- All mode selections are traceable to brief version control

### Doctrine Integration
**Status**: ✅ COMPATIBLE
- Doctrine is already hashed and included in inputs_hash
- Generation modes don't affect doctrine loading or versioning
- Same doctrine version → deterministic with or without variants
- Doctrine hash participates in inputs_hash regardless of mode

### Registry-Based Job Routing
**Status**: ✅ COMPATIBLE
- Generation modes are job-internal; registry routes by `job_type` only
- Each job_type can independently choose to support certain modes
- Currently instagram_copy supports all three modes
- Future job types can be restricted to specific modes via code

## Backward Compatibility Confirmation

### API Surface
**Status**: ✅ UNCHANGED
```
POST /jobs/run
- Input: { job_ref, params }
- Output: { job_id, run_id }
```
- No parameter changes
- No return value changes
- Existing clients unaffected

### Artifact Structure
**Status**: ✅ BACKWARD COMPATIBLE
- `outputs/instagram_captions.md` is ALWAYS present (even in variants/format modes)
- Existing tools reading `outputs/instagram_captions.md` continue to work
- Mode A (default) produces identical output to pre-Stage-5 code
- Mode B/C add NEW files; they don't replace or rename the primary output

### Manifest JSON Structure
**Status**: ✅ ADDITIVE ONLY
- `generation_metadata` is a NEW optional field (default: empty dict)
- Existing manifest consumers tolerant of unknown fields
- Schema version unchanged (1.1.0); no required field removals

### Default Behavior
**Status**: ✅ PRESERVED
- When brief omits `generation_mode`, defaults to "single"
- When brief omits `caption_variants`, defaults to 1
- When brief omits `output_formats`, defaults to ["md"]
- Result: identical outputs to pre-Stage-5 code (Mode A only, markdown output)

## Filesystem Authority Confirmation

### Canonical Locations
**Status**: ✅ PRESERVED
```
artifacts/<job_id>/<run_id>/
  ├── inputs/
  │   ├── brief.resolved.json (includes generation_mode)
  │   ├── context.resolved.json
  │   ├── model_config.json
  │   └── doctrine.resolved.json
  ├── outputs/
  │   ├── instagram_captions.md (always present)
  │   ├── variants/ (Mode B only)
  │   │   ├── 01.md, 02.md, ...
  │   │   └── variants.json
  │   ├── instagram_captions.json (Mode C only)
  │   └── instagram_captions.yaml (Mode C only)
  └── manifest.json (includes generation_metadata)
```

### Manifest as Source of Truth
**Status**: ✅ PRESERVED
- All outputs recorded in `manifest.artifacts` with content hashes
- Manifest includes complete `generation_metadata`
- DB reindex can rebuild index from manifest alone
- No database writes are required for functionality

### Deterministic Reproducibility
**Status**: ✅ GUARANTEED
- Given artifact directory + manifest, can reproduce outputs
- Seeds stored in manifest → deterministic variant regeneration if needed
- Filesystem is sufficient source of truth; DB is optional index

## Definition of Done - Stage 5

✅ **No Silent Drift**
- Mode in brief.resolved.json, frozen to disk
- Included in inputs_hash computation
- Changing mode changes run_id

✅ **Determinism Preserved**
- Variant generation uses deterministic seeds from inputs_hash
- Seeds recorded in manifest
- Same inputs → identical outputs (deterministic model)

✅ **API Compatibility**
- POST /jobs/run unchanged
- Response format unchanged
- Default behavior identical to pre-Stage-5

✅ **Manifest Completeness**
- Snapshot paths and hashes present
- Generation mode metadata recorded
- All outputs hashed and listed

✅ **Filesystem Reproducibility**
- Run reproducible from snapshot directory alone
- Manifest contains all required metadata
- No database required

✅ **Smoke Tests**
- make smoke_determinism still passes (backward compatibility)
- make smoke_generation_modes passes (new functionality)

## Testing Coverage

### smoke_determinism.py (Existing - Must Still Pass)
- 12 tests validating Phase 1.0 determinism invariants
- Tests pass with new code because Mode A (default) is backward compatible
- Snapshot hashing, run_id derivation, idempotent replay all unchanged

### smoke_generation_modes.py (New - Stage 5 Specific)
1. **Test 1: Mode A (Single)**
   - Executes twice with same brief
   - Asserts identical run_id (determinism)
   - Verifies `outputs/instagram_captions.md` exists
   - Cleanup

2. **Test 2: Mode B (Variants)**
   - Brief: `generation_mode="variants"`, `caption_variants=3`
   - Executes twice
   - Asserts identical run_id (inputs_hash determinism)
   - Verifies 3 seeds in `generation_metadata`
   - Verifies variant files: `01.md`, `02.md`, `03.md`, `variants.json`
   - Cleanup

3. **Test 3: Mode C (Format)**
   - Brief: `generation_mode="format"`, `output_formats=["md", "json", "yaml"]`
   - Executes once
   - Verifies all three output files exist
   - Validates JSON and YAML are well-formed
   - Cleanup

4. **Test 4: Backward Compatibility**
   - Brief with no `generation_mode` override (uses default)
   - Asserts `generation_metadata.generation_mode == "single"`
   - Asserts no variant/ files created
   - Cleanup

## Non-Goals (Explicit Out-of-Scope)

❌ Free-form prompt experiments (no parametric prompting)
❌ Ad-hoc schema evolution (modes are enumerated, fixed)
❌ Nondeterministic runs under same run_id (guaranteed deterministic)
❌ Dynamic seed selection (seeds are deterministic functions of inputs_hash)

## Future Extensions

Possible Stage 6+ additions (not in Stage 5):
- Mode D: Registry expansion (support output to artifact registries)
- Mode E: Post-processing (apply transformations to variant outputs)
- Conditional modes (based on job_type or brief properties)
- Mode-specific sampling strategies (e.g., diversity-driven variant generation)

All future extensions must preserve:
- Snapshot-based inputs
- Deterministic run_id
- Governance job_id
- Filesystem authority
- Backward compatibility with Stage 5 outputs
