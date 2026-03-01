# STAGE 11: Observability & Langfuse Integration

## Overview

Stage 11 enhances observability capabilities via Langfuse tracing while preserving all Phase 1.0 determinism guarantees. The framework provides structured tracing, LLM generation tracking, and performance instrumentation without affecting run_id derivation or canonical snapshots.

**Key Principle:** Observability is SECONDARY to execution. Traces link to governance identifiers (job_id, run_id) but never participate in determinism.

---

## Architecture

### Observability Philosophy

**Primary vs. Secondary Data:**
```
PRIMARY (Deterministic):
- Canonical input snapshots (inputs/)
- inputs_hash (from snapshot hashes)
- run_id (from inputs_hash)
- Output files (outputs/)
- manifest.json

SECONDARY (Observability):
- Runtime trace IDs (not serialized in deterministic manifest.json)
- Trace spans, generations, metadata
- Performance metrics
- LLM usage tracking
```

**Guarantee:** Secondary data NEVER affects primary data.

---

### Phase 1.0 Determinism Preservation

| Invariant | Mechanism | Status |
|-----------|-----------|--------|
| 1. Canonical Input Snapshots | Trace IDs never written to inputs/ directory | ✅ PRESERVED |
| 2. Deterministic run_id | Tracing happens AFTER run_id derivation | ✅ PRESERVED |
| 3. Governance job_id | job_id passed TO traces, not derived FROM traces | ✅ PRESERVED |
| 4. Doctrine as Hashed Input | Doctrine hash participates in inputs_hash, traces for observability only | ✅ PRESERVED |
| 5. Filesystem Authoritative | Trace data stored in Langfuse (separate from artifacts) | ✅ PRESERVED |
| 6. No Silent Drift | Trace IDs excluded from inputs_hash, logged separately | ✅ PRESERVED |
| 7. Backward Compatibility | Nondeterministic fields excluded from deterministic manifest serialization | ✅ PRESERVED |

---

### Module Structure

#### 1. `sigilzero/core/langfuse_client.py` (Enhanced)

**Core Langfuse Integration:**

```python
class LangfuseClient:
    """Thin wrapper for Langfuse tracing.
    
    Features:
    - Optional enablement (LANGFUSE_* env vars)
    - Silent failures (don't break execution)
    - No-op implementations when disabled
    - Context managers for traces and spans
    """
    
    def trace(...) -> Trace
    def span(...) -> Span
    def generation(...) -> Generation
    def trace_context(...) -> ContextManager[Trace]
    def span_context(...) -> ContextManager[Span]


def get_langfuse() -> Optional[LangfuseClient]:
    """Get global Langfuse client (None if disabled)"""


@trace_function(name, capture_args, capture_result):
    """Decorator for tracing function execution"""
```

**Configuration:**
- `LANGFUSE_PUBLIC_KEY`: Public API key
- `LANGFUSE_SECRET_KEY`: Secret API key
- `LANGFUSE_HOST`: Langfuse server URL (e.g., http://localhost:3000)

**Behavior:**
- If env vars missing → disabled (degraded mode)
- If Langfuse import fails → disabled (graceful degradation)
- If connection fails → disabled (silent failure)
- Returns no-op objects when disabled (code still works)

---

#### 2. `sigilzero/core/observability.py` (New)

**Standardized Tracing Patterns:**

```python
# Top-level pipeline trace
trace, trace_id = trace_pipeline_execution(
    job_id, run_id, job_type, brand, inputs_hash, queue_job_id
)

# Pipeline step tracing
with trace_step(trace_id, "step_name", metadata={...}):
    # ... step code ...
    pass

# LLM generation tracking
trace_llm_call(
    trace_id, name, model, prompt, response, usage, metadata
)

# Domain-specific tracing
trace_doctrine_load(trace_id, doctrine_id, version, path, sha256)
trace_context_retrieval(trace_id, mode, files_retrieved, query, top_k)
trace_snapshot_creation(trace_id, snapshot_name, hash, bytes)
trace_output_generation(trace_id, output_files, total_bytes, metadata)

# Finalize trace
finalize_trace(trace, status, error, artifacts)

# Check if enabled
if is_observability_enabled():
    # ... optional instrumentation ...
```

**Key Features:**
- All functions handle `None` trace_id (disabled mode)
- Consistent metadata structure across pipelines
- Governance identifiers included (job_id, run_id)
- Silent failures (don't break execution)

---

### Execution Flow

**Phase 1.0 Determinism-Preserving Order:**

```
1. Load brief.yaml (governance)
   ↓
2. Resolve context & model config
   ↓
3. Create input snapshots (canonical JSON)
   ↓
4. Compute snapshot hashes (SHA256)
   ↓
5. Compute inputs_hash (from snapshot hashes)
   ↓
6. Derive run_id (from inputs_hash)
   ↓
7. START TRACING (trace_pipeline_execution)
   ├─ Include job_id, run_id in metadata
   ├─ Trace ID returned but not stored in snapshots
    └─ Trace ID excluded from deterministic manifest serialization
   ↓
8. Execute pipeline with tracing
   ├─ Trace doctrine loading
   ├─ Trace LLM calls
   ├─ Trace output generation
   └─ All traces link to trace_id from step 7
   ↓
9. Finalize trace (success/failure status)
   ↓
10. Write manifest.json (deterministic serialization excludes trace/timestamp fields)
```

**Critical:** Steps 1-6 happen BEFORE tracing starts. run_id is deterministic and independent of observability.

---

### Integration Patterns

#### Pattern 1: Pipeline Instrumentation

**Before (Stage 10):**
```python
def run_instagram_copy_pipeline(brief, context, model_config, doctrine):
    # ... create snapshots ...
    inputs_hash = compute_inputs_hash(snapshot_hashes)
    run_id = derive_run_id(inputs_hash)
    
    # Basic tracing (minimal)
    lf = get_langfuse()
    trace_id = None
    if lf:
        trace = lf.trace(name="job:instagram_copy")
        trace_id = trace.id
    
    # ... execute pipeline ...
    
    manifest = RunManifest(
        job_id=brief.job_id,
        run_id=run_id,
        langfuse_trace_id=trace_id,
        ...
    )
```

**After (Stage 11):**
```python
def run_instagram_copy_pipeline(brief, context, model_config, doctrine):
    # ... create snapshots ...
    inputs_hash = compute_inputs_hash(snapshot_hashes)
    run_id = derive_run_id(inputs_hash)
    
    # Enhanced tracing with metadata
    trace, trace_id = trace_pipeline_execution(
        job_id=brief.job_id,
        run_id=run_id,
        job_type=brief.job_type,
        brand=brief.brand,
        inputs_hash=inputs_hash,
        queue_job_id=queue_job_id,
    )
    
    try:
        # Trace doctrine loading
        with trace_step(trace_id, "load_doctrine"):
            doctrine = load_doctrine(...)
            trace_doctrine_load(trace_id, doctrine_id, version, path, sha256)
        
        # Trace LLM call
        with trace_step(trace_id, "generate_captions"):
            response = openai.ChatCompletion.create(...)
            trace_llm_call(
                trace_id, "caption_generation", "gpt-4",
                prompt, response.choices[0].message.content,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            )
        
        # Finalize success
        finalize_trace(trace, "succeeded", artifacts=manifest.artifacts)
    
    except Exception as e:
        finalize_trace(trace, "failed", error=str(e))
        raise
    
    manifest = RunManifest(
        job_id=brief.job_id,
        run_id=run_id,
        langfuse_trace_id=trace_id,
        ...
    )
```

---

#### Pattern 2: Conditional Instrumentation

```python
# Always works (with or without Langfuse)
with trace_step(trace_id, "expensive_operation"):
    result = expensive_operation()

# Optional extra instrumentation
if is_observability_enabled():
    # Add detailed custom traces
    lf = get_langfuse()
    with lf.span_context(trace_id, "detailed_sub_operation"):
        # ... detailed instrumentation ...
        pass
```

---

#### Pattern 3: Function Decoration

```python
@trace_function(name="generate_caption", capture_result=True)
def generate_caption(brief: BriefSpec, context: str) -> str:
    """Generate Instagram caption.
    
    Tracing:
    - Automatically traced if Langfuse enabled
    - Captures function result in trace output
    - Silent failure if tracing unavailable
    """
    prompt = render_prompt(brief, context)
    response = call_openai(prompt)
    return response.choices[0].message.content
```

---

## Testing & Validation

### Smoke Test Coverage

**`scripts/smoke_observability.py`** (8 tests)

1. **Graceful Degradation**: System works when Langfuse disabled
2. **Determinism Preservation**: Trace IDs excluded from inputs_hash/run_id
3. **Execution Order**: Tracing happens AFTER run_id derivation
4. **Snapshot Isolation**: Trace IDs never in input snapshots
5. **Silent Failures**: Tracing errors don't break execution
6. **Governance Metadata**: job_id/run_id included in traces
7. **Utility Consistency**: All observability functions handle None trace_id
8. **Context Managers**: trace_step() works correctly

**Test Results:**
```bash
$ python3 scripts/smoke_observability.py

✅ ALL TESTS PASSED (8/8)

Phase 1.0 Determinism Guarantees Verified:
  ✓ run_id derivation unchanged (tracing happens after)
  ✓ inputs_hash unchanged (trace IDs excluded)
  ✓ Trace IDs never in input snapshots
  ✓ System works without Langfuse (graceful degradation)
  ✓ Tracing failures are silent (don't break execution)
  ✓ Governance identifiers included in trace metadata
  ✓ Observability utilities provide consistent patterns
```

---

### Determinism Validation

**Test 1: Trace IDs Excluded from inputs_hash**

```python
# Compute hash WITHOUT tracing
snapshot_hashes = {"brief": "abc", "context": "def", "model_config": "ghi"}
inputs_hash_1 = compute_inputs_hash(snapshot_hashes)
run_id_1 = derive_run_id(inputs_hash_1)

# Start tracing (trace_id excluded from deterministic manifest serialization)
trace, trace_id = trace_pipeline_execution(...)

# Compute hash again (should be IDENTICAL)
inputs_hash_2 = compute_inputs_hash(snapshot_hashes)
run_id_2 = derive_run_id(inputs_hash_2)

assert inputs_hash_1 == inputs_hash_2  # ✅ PASS
assert run_id_1 == run_id_2  # ✅ PASS
```

**Test 2: Manifest Structure**

```json
{
  "schema_version": "1.2.0",
  "job_id": "ig-test-001",
  "run_id": "abc123def456",
  "inputs_hash": "def456789012",
  "input_snapshots": {
    "brief": {
      "path": "inputs/brief.resolved.json",
      "sha256": "abc123",
      "bytes": 1024
      // NO trace_id here
    }
  },
  ...
}
```

**Guarantee:** Deterministic `manifest.json` serialization excludes `langfuse_trace_id`, `started_at`, and `finished_at`. Snapshot hashes are computed without trace data.

---

## Operational Procedures

### Enable Langfuse

**1. Environment Configuration**

```bash
# In .env file or environment
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="http://localhost:3000"  # or production URL
```

**2. Verify Enablement**

```python
from sigilzero.core.observability import is_observability_enabled

if is_observability_enabled():
    print("✅ Langfuse observability enabled")
else:
    print("⚠️  Langfuse observability disabled (degraded mode)")
```

**3. Check Traces in Langfuse UI**

- Navigate to Langfuse dashboard (http://localhost:3000)
- Filter by tags: `instagram_copy`, brand name
- Search by metadata: `job_id`, `run_id`
- View trace hierarchy: pipeline → steps → generations

---

### Disable Langfuse

**Option 1: Remove environment variables**

```bash
unset LANGFUSE_PUBLIC_KEY
unset LANGFUSE_SECRET_KEY
unset LANGFUSE_HOST
```

**Option 2: Leave as-is**

System automatically degrades to no-op mode if:
- Environment variables missing
- Langfuse server unreachable
- Langfuse library import fails

**No code changes needed.** All tracing operations handle disabled state gracefully.

---

### Debug Tracing Issues

**Symptom:** Traces not appearing in Langfuse

**Checklist:**
1. Verify environment variables set correctly
2. Check Langfuse server is running (http://localhost:3000)
3. Check network connectivity from app to Langfuse
4. Verify public/secret keys are valid
5. Check logs for connection errors

**Test Connection:**

```python
from sigilzero.core.langfuse_client import get_langfuse

lf = get_langfuse()
if lf is None:
    print("❌ Langfuse client disabled")
    # Check environment variables
else:
    print("✅ Langfuse client enabled")
    trace = lf.trace(name="test_trace", metadata={"test": True})
    print(f"   Trace ID: {trace.id}")
```

---

### Monitoring & Alerting

**Key Metrics to Monitor:**

1. **Observability Health**
   - Langfuse enablement rate (% of runs with trace_id)
   - Trace creation success rate
   - Langfuse server availability

2. **Pipeline Performance**
   - Average execution time per job_type
   - LLM token usage (prompt/completion/total)
   - Generation success rate

3. **Cost Tracking**
   - Total tokens per brand/job_type
   - Estimated costs (tokens × model pricing)
   - Cost per successful output

**Langfuse Queries:**

```sql
-- Average execution time by job_type
SELECT
  metadata->>'job_type' as job_type,
  AVG(duration_ms) as avg_duration_ms
FROM traces
WHERE name LIKE 'job:%'
GROUP BY job_type;

-- Token usage by brand
SELECT
  metadata->>'brand' as brand,
  SUM((usage->>'total_tokens')::int) as total_tokens
FROM generations
WHERE trace_id IN (
  SELECT id FROM traces WHERE metadata->>'brand' IS NOT NULL
)
GROUP BY brand;

-- Error rate by job_type
SELECT
  metadata->>'job_type' as job_type,
  COUNT(*) FILTER (WHERE output->>'status' = 'failed') as failures,
  COUNT(*) as total,
  ROUND(100.0 * COUNT(*) FILTER (WHERE output->>'status' = 'failed') / COUNT(*), 2) as error_rate_pct
FROM traces
WHERE name LIKE 'job:%'
GROUP BY job_type;
```

---

## Backward Compatibility

### Manifest Schema Changes

**v1.2.0 → v1.2.0 (No Breaking Changes):**

- `langfuse_trace_id` remains available in-memory but is excluded from deterministic serialization
- Stage 11 enhances HOW traces are created (not schema)
- All existing manifests remain valid
- Old code ignores enhanced trace metadata (Pydantic default)

### Client Compatibility

| Client Version | Reads v1.2.0 | Writes v1.2.0 | Observability |
|----------------|--------------|---------------|---------------|
| v1.2 (pre-Stage 11) | ✅ Yes | ✅ Yes | Basic (trace_id only) |
| v1.2 (post-Stage 11) | ✅ Yes | ✅ Yes | Enhanced (full metadata) |

**Guarantee:** Old clients work unchanged. Enhanced observability is opt-in.

### API Surface

**POST /jobs/run:**
- Request: Unchanged (brief.yaml + params)
- Response: Unchanged (job_id, run_id, status)
- Observability: Transparent (happens internally)

**GET /jobs/{id}:**
- Request: Unchanged (job_id or run_id)
- Response: Unchanged (deterministic manifest serialization)
- Observability: Runtime metadata remains external to deterministic manifest serialization

---

## Definition of Done: Stage 11

### Code Implementation ✅

- [x] Enhanced `langfuse_client.py` with context managers, generation tracking
- [x] New `observability.py` module with standardized tracing patterns
- [x] Comprehensive smoke test suite (8 tests, all passing)
- [x] All traces link to governance identifiers (job_id, run_id)
- [x] Silent failures (tracing errors don't break execution)

### Determinism Validation ✅

All 7 Phase 1.0 invariants preserved:

- [x] **Invariant 1**: Trace IDs never written to inputs/ directory
- [x] **Invariant 2**: Tracing happens AFTER run_id derivation
- [x] **Invariant 3**: job_id passed TO traces (not derived FROM traces)
- [x] **Invariant 4**: Doctrine hash in inputs_hash, traces for observability only
- [x] **Invariant 5**: Traces stored in Langfuse (separate from artifacts/)
- [x] **Invariant 6**: Trace IDs excluded from inputs_hash
- [x] **Invariant 7**: Nondeterministic fields excluded from deterministic manifest serialization

### Governance Alignment ✅

- [x] job_id semantics unchanged
- [x] Trace metadata includes governance identifiers
- [x] Filesystem remains authoritative (traces don't affect artifacts)
- [x] Observability is secondary (execution continues if tracing fails)

### Backward Compatibility ✅

- [x] No manifest schema changes
- [x] Old clients work unchanged
- [x] API surface unchanged
- [x] Graceful degradation when Langfuse disabled

### Documentation ✅

- [x] Architecture document (this file)
- [x] Integration patterns (pipeline instrumentation)
- [x] Operational procedures (enable/disable, debug)
- [x] Testing & validation (8 smoke tests)
- [x] Monitoring & alerting (key metrics, queries)

---

## Architect Reporting Block

### 1. Structural Changes Summary

**Files Enhanced:**
- `app/sigilzero/core/langfuse_client.py` (+200 lines)
  - Added context managers (trace_context, span_context)
  - Added generation() method for LLM tracking
  - Enhanced trace() with tags, session_id, user_id support
  - Added trace_function() decorator

**Files Created:**
- `app/sigilzero/core/observability.py` (400 lines)
  - trace_pipeline_execution(): Top-level pipeline tracing
  - trace_step(): Context manager for pipeline steps
  - trace_llm_call(): LLM generation tracking
  - trace_doctrine_load(), trace_context_retrieval(), etc.
  - finalize_trace(): Trace completion with status
  - is_observability_enabled(): Check if tracing enabled

- `app/scripts/smoke_observability.py` (300 lines)
  - 8 comprehensive smoke tests
  - Determinism invariant validation
  - Graceful degradation testing
  - Silent failure verification

**No Breaking Changes:**
- All changes additive (new functions, enhanced methods)
- Existing pipeline code continues to work
- Manifest schema unchanged

---

### 2. Determinism Validation

**Execution Order Guarantee:**

```
Snapshots → Hashes → inputs_hash → run_id → START TRACING
    ↓          ↓          ↓           ↓            ↓
UNCHANGED  UNCHANGED  UNCHANGED   UNCHANGED    SEPARATE
```

**Test Evidence:**

```python
# Test: Same snapshots → Same run_id (with/without tracing)
snapshot_hashes = {"brief": "abc", "context": "def", ...}

# Without tracing
inputs_hash_1 = compute_inputs_hash(snapshot_hashes)
run_id_1 = derive_run_id(inputs_hash_1)
# run_id_1 = "eb8e4cd552fdf661f062f84d481fe547"

# Start tracing
trace, trace_id = trace_pipeline_execution(...)

# With tracing (snapshots unchanged)
inputs_hash_2 = compute_inputs_hash(snapshot_hashes)
run_id_2 = derive_run_id(inputs_hash_2)
# run_id_2 = "eb8e4cd552fdf661f062f84d481fe547"

assert run_id_1 == run_id_2  # ✅ PASS (determinism preserved)
```

**Smoke Test Results:**
```
✅ ALL TESTS PASSED (8/8)
  ✓ run_id derivation unchanged
  ✓ inputs_hash unchanged
  ✓ Trace IDs never in snapshot files
  ✓ Graceful degradation when disabled
  ✓ Silent failures don't break execution
```

---

### 3. Governance Alignment

**job_id Integration:**
- job_id passed TO trace metadata (governance → observability)
- job_id NOT derived FROM traces (observability → governance) ✗
- Traces filterable by job_id in Langfuse UI

**run_id Integration:**
- run_id derived BEFORE tracing starts
- run_id included in trace metadata for linking
- Traces findable via run_id search

**Trace Hierarchy:**
```
Trace (job:instagram_copy)
├─ metadata: {job_id, run_id, brand, inputs_hash}
├─ Span: load_doctrine
│  └─ metadata: {doctrine_id, version, sha256}
├─ Span: generate_captions
│  └─ Generation: caption_generation
│     ├─ model: gpt-4
│     ├─ usage: {prompt_tokens, completion_tokens}
│     └─ output: {...}
└─ output: {status, artifacts}
```

---

### 4. Backward Compatibility Confirmation

**Manifest Schema:**
- No changes to v1.2.0 schema
- `langfuse_trace_id` exists on the model but is excluded from deterministic serialization
- Stage 11 enhances trace creation logic (not schema)

**API Surface:**
- POST /jobs/run: Unchanged (request/response)
- GET /jobs/{id}: Unchanged (manifest structure)
- Observability transparent to API clients

**Pipeline Code:**
- Existing pipelines work unchanged
- Enhanced instrumentation opt-in (via observability.py)
- Old tracing patterns still work (deprecated but functional)

**Deployment:**
- No migration needed (schema unchanged)
- No database changes (manifest fields unchanged)
- Langfuse optional (system works without it)

---

### 5. Filesystem Authority Confirmation

**Trace Storage:**
- Traces stored in **Langfuse database** (not artifacts/)
- Manifests stored in **artifacts/ directory** (filesystem authoritative)
- Trace identifiers are observability-only and excluded from deterministic manifest serialization

**Data Flow:**
```
Pipeline Execution
    ↓
artifacts/<job_id>/<run_id>/
├─ inputs/
│  ├─ brief.resolved.json (deterministic)
│  ├─ context.resolved.json (deterministic)
│  └─ ... (no trace data)
├─ outputs/
│  └─ ... (deterministic)
└─ manifest.json
   ├─ run_id (deterministic)
   ├─ inputs_hash (deterministic)
    └─ deterministic fields only                         
Langfuse Database (Separate)
├─ Traces                                             │
│  └─ id: trace-xyz-789
│     ├─ metadata: {job_id, run_id, brand}
│     ├─ spans: [...]
│     └─ generations: [...]
└─ Metrics derived from traces
```

**Filesystem Authority Preserved:**
- Traces are SECONDARY (observability)
- Artifacts are PRIMARY (execution results)
- System works without Langfuse (degraded observability, full functionality)
- Reindex rebuilds DB from artifacts (ignores Langfuse)

---

## Risk Assessment

### Low Risk ✅

- **Determinism preserved**: All 7 invariants validated
- **Backward compatible**: No schema changes, old clients work
- **Optional dependency**: System works without Langfuse
- **Silent failures**: Tracing errors don't break execution
- **Comprehensive testing**: 8 smoke tests, all passing

### Medium Risk ⚠️

- **Trace data volume**: High-volume pipelines generate many traces
- **Langfuse server load**: Needs capacity planning
- **Network latency**: Trace writes may add latency (async recommended)

### Mitigation Strategies

1. **Volume Management**
   - Configure Langfuse data retention (auto-delete old traces)
   - Sample tracing (trace 10% of runs in production)
   - Disable tracing for low-priority jobs

2. **Performance**
   - Use async trace writes (don't block execution)
   - Batch trace data (reduce network calls)
   - Monitor Langfuse server performance

3. **Operational**
   - Deploy Langfuse with monitoring (health checks)
   - Set up alerts for Langfuse downtime
   - Document degraded mode behavior

---

## Next Steps (Beyond Stage 11)

### Immediate (Post-Stage 11)
- [ ] Deploy enhanced observability to staging
- [ ] Validate trace data appears in Langfuse UI
- [ ] Configure Langfuse data retention policy
- [ ] Set up Langfuse monitoring alerts

### Future Enhancements
- [ ] Add trace sampling (configurable rate)
- [ ] Implement custom metrics (cost tracking, quality scores)
- [ ] Add user attribution (if applicable)
- [ ] Create observability dashboard (Grafana + Langfuse)
- [ ] Add trace-based debugging tools

---

## Conclusion

Stage 11 delivers **production-ready observability** via Langfuse while preserving all Phase 1.0 determinism guardrails.

**Key Achievements:**
- ✅ Enhanced Langfuse client with context managers, generation tracking
- ✅ Standardized observability patterns (trace_pipeline_execution, trace_step, etc.)
- ✅ 8 smoke tests passing (determinism + graceful degradation)
- ✅ No breaking changes (backward compatible)
- ✅ Comprehensive documentation (architecture + operations)

**Production Readiness:** YES (with Langfuse server deployment)

**Stage 11 is COMPLETE and ready for staging deployment.**
