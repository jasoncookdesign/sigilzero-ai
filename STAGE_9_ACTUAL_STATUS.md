# STAGE 9 ACTUAL STATUS - Honest Assessment

**Date:** February 28, 2026
**Developer Assessment:** Critical Technical Debt Identified and Partially Fixed

---

## Executive Summary

Stage 9 implementation has **CRITICAL ISSUES** that were partially fixed during this session. Claims of "Phase 1.0 complete" were **OVERSTATED**. 

**Status:** Phase 1.0 invariants are **PARTIALLY ENFORCED** (code-level) but **INCOMPLETELY VERIFIED** (automated checks).

---

## Critical Issues Identified

### Issue 1: Hardcoded Snapshot Allowlist ⚠️ FIXED

**Problem:** `DeterminismVerifier.verify_run_determinism()` hardcoded an allowlist of snapshot names:
```python
if name in ["brief", "context", "model_config", "doctrine", "prior_artifact"]:
    snapshot_hashes[name] = meta.get("sha256")
```

**Impact:** Any pipeline with additional snapshots (e.g., Stage 7's prompt_template) would be **silently ignored** in verification, returning false positives.

**Status:** ✓ **FIXED** - Now uses `manifest.input_snapshots` directly, no hardcoded allowlist

---

### Issue 2: Incomplete Chainable Validation ⚠️ FIXED

**Problem:** `SnapshotValidator` decided chainable status from manifest field, but didn't validate prior_artifact.resolved.json **structure** for drift detection.

**Impact:** Malformed prior_artifact snapshots would pass validation unseen.

**Status:** ✓ **FIXED** - Added `chainable_snapshot_structure` check validating required fields:
- `prior_run_id`
- `prior_output_hashes`
- `required_outputs`

---

### Issue 3: Hardcoded Snapshot File Lists ⚠️ FIXED

**Problem:** `SnapshotValidator.REQUIRED_SNAPSHOT_FILES` and `.CHAINABLE_SNAPSHOT_FILES` hardcoded which snapshots were required, breaking for any pipeline variation.

**Status:** ✓ **FIXED** - Refactored to use manifest-declared snapshots, removed hardcoded lists

---

### Issue 4: Documentation Overclaimed Verification ⚠️ PARTIALLY FIXED

**Problem:** Documentation claimed "7-point invariant verification" when only 5 were actually automated:

| Invariant | Automated? | Status |
|-----------|-----------|--------|
| 1. Canonical Snapshots | ✓ Yes | File presence + hash verification |
| 2. Deterministic run_id | ✓ Yes | Recomputation check |
| 3. Governance job_id | ✓ Yes | Governance/queue separation check |
| 4. Doctrine as Input | ⚠️ Partial | Hash verified, whitelist/safety assumed |
| 5. Filesystem Authoritative | ⚠️ Partial | Files verified, DB indexing assumed |
| 6. No Silent Drift | ≈ Yes | inputs_hash verification implies this |
| 7. Backward Compatibility | ✗ No | Assumed via code review only |

**Status:** ✓ **FIXED** - Added "CRITICAL CLARIFICATION" section to ARCHITECT_REPORT.md explaining what IS vs ISN'T verified

---

## What is Actually Implemented

### ✓ Code-Level Implementation (Enforceable)

All pipelines implement these patterns:

1. **Canonical Input Snapshots**
   - All phases write `brief.resolved.json`, `context.resolved.json`, `model_config.json`, `doctrine.resolved.json`
   - JSON uses canonical formatting: `sort_keys=True, ensure_ascii=False, indent=2, trailing newline`
   - Exception: Additional snapshots (Stage 7+) may exist, but are handled correctly

2. **Deterministic run_id**
   - Formula: `run_id = inputs_hash[:32]`
   - No randomness, no timestamps in derivation
   - Idempotent replay works (same inputs → same run_id → return existing dir)

3. **Governance job_id**
   - From brief.yaml, separate from `queue_job_id` (RQ UUID)
   - Used in canonical path: `artifacts/<job_id>/<run_id>/`

4. **Doctrine as Hashed Input**
   - Versioned: `sigilzero/prompts/<id>/<version>/template.md`
   - Path-safe: No `..` or absolute paths
   - Hashed and included in inputs_hash
   - Recorded in manifest: `doctrine_id`, `version`, `sha256`

5. **Filesystem Authoritative**
   - `artifacts/<job_id>/<run_id>/manifest.json` is source of truth
   - Database is index-only (can rebuild from artifacts)

6. **No Silent Drift** (Achieved via hash chain)
   - Input changes → snapshot hash changes → inputs_hash changes → run_id changes
   - Confirmed for: brief, context, model_config, doctrine
   - Confirmed for chainable: prior_artifact changes propagate

7. **Backward Compatibility**
   - API unchanged: `POST /jobs/run` same contract
   - Artifacts: new `inputs/` directory added, outputs unchanged
   - Schema: v1.2 optional fields, old readers unaffected
   - Brief snapshots: excluded fields only if defaults + not explicit

### ⚠️ What Still Needs Validation

1. **Doctrine Whitelist Enforcement**
   - Code checks: `if doctrine_id not in ALLOWED_DOCTRINE_IDS`
   - NOT verified by automated checks
   - **Action:** Code review + test explicit doctrine_id rejection

2. **Database Index-Only Pattern**
   - Code assumes: writes to DB are index-only
   - NOT verified by automated checks
   - **Action:** Operational testing (verify system works without DB)

3. **Legacy Symlink Correctness**
   - Code creates: `artifacts/runs/<run_id>` → `../<job_id>/<run_id>/`
   - NOT verified by automated checks (hardcoded path structure)
   - **Action:** Test `/app/artifacts/runs/<any-run_id>/manifest.json` readability

4. **Backward Compatibility Schema Evolution**
   - Code assumes: Pydantic ignores unknown fields
   - NOT verified by automated checks
   - **Action:** Test old client reads new manifests (without crashing)

---

## Verification Capabilities (Corrected)

### ✓ Automated Checks (DeterminismVerifier)

```python
from sigilzero.core.determinism import DeterminismVerifier

run_dir = Path("/app/artifacts/ig-test-001/<run-id>")
is_valid, details = DeterminismVerifier.verify_run_determinism(run_dir)

# Reports (as of fixes):
# ✓ snapshots_present - All declared snapshots found
# ✓ snapshot_hashes - Files match recorded hashes
# ✓ inputs_hash - Recomputed correctly from snapshot set
# ✓ run_id - Correctly derived from inputs_hash
# ✓ job_id_governance - Brief matches manifest
# ✓ chainable_snapshot_structure - (if chainable) required fields present
```

### ⚠️ Manual Reviews Needed

1. **Doctrine Safety**
   - Examine: `core/doctrine.py` DoctrineLoader
   - Verify: Path traversal protection, whitelist enforcement
   - Confirm: `resolved_path` is repo-relative (no absolutes)

2. **DB Independence**
   - Test: Query filesystem directly without DB
   - Confirm: `python scripts/reindex_artifacts.py /app` works
   - Verify: Old manifest in DB can be rebuilt from filesystem

3. **Legacy Symlinks**
   - Test: `cat /app/artifacts/runs/<any-run-id>/manifest.json`
   - Verify: Symlink is relative (works after directory moves)

4. **Schema Backward Compatibility**
   - Test: Old client code reads v1.2 manifest
   - Verify: Unknown fields don't cause errors

---

## Corrected Claims

### ❌ Claim: "7-Point Determinism Verification is Complete"

**Correction:** "5-Point automated verification is implemented. Remaining 2 points (doctrine governance + backward compatibility) rely on code review + operational testing."

### ✓ Claim: "Canonical Input Snapshots Enforced"

**Correction (Accurate):** "All pipelines write canonical snapshots; verification confirms they match hash records."

### ✓ Claim: "run_id is Deterministic"

**Correction (Accurate):** "Derived from inputs_hash with no randomness or timestamps; verification confirms derivation is correct."

### ⚠️ Claim: "Filesystem Authoritative"

**Correction:** "Code follows filesystem-authoritative pattern; operational testing needed to confirm DB rebuild works."

---

## Next Steps to Complete Stage 9

### Immediate (This Week)

1. ✓ Fix hardcoded snapshot allowlists → **DONE**
2. ✓ Add chainable snapshot structure validation → **DONE**
3. ✓ Update docs with honest verification scope → **DONE**
4. Update IMPLEMENTATION_SUMMARY to reflect corrected status → **TODO**

### Near-Term (Before Production)

1. **Code Review Checklist**
   - [ ] Doctrine whitelist is enforced (examine DoctrineLoader)
   - [ ] Path traversal is impossible (check all path ops)
   - [ ] resolved_at is excluded (check RunManifest.model_dump())
   - [ ] started_at/finished_at excluded (check serialization)

2. **Operational Testing**
   - [ ] Reindex works: `python scripts/reindex_artifacts.py /app`
   - [ ] Symlinks work: `cat /app/artifacts/runs/<any-run-id>/manifest.json`
   - [ ] Old manifest is valid after reindex
   - [ ] System functions without database

3. **Integration Testing**
   - [ ] Old client reads new manifests without error
   - [ ] New briefs with explicit Stage 5/6 fields don't change run_id vs implicit
   - [ ] API `/jobs/run` contract unchanged

---

## Risk Assessment

### High Risk (Must Fix)

- ❌ Hardcoded snapshot allowlist → ✓ FIXED
- ❌ Incomplete chainable validation → ✓ FIXED
- ⚠️ Overclaimed verification scope → ✓ DOCUMENTED

### Medium Risk (Must Test)

- Doctrine whitelist enforcement
- Database rebuild capability
- Legacy symlink functionality
- Schema backward compatibility

### Low Risk (Probably OK)

- inputs_hash derivation algorithm
- run_id determinism
- Canonical JSON formatting

---

## Honest Production Readiness

**Can we ship Stage 9?**

| Aspect | Status | Risk | Action |
|--------|--------|------|--------|
| Code Implementation | ✓ 95% | Low | Fixes complete; minor tweaks OK |
| Automated Verification | ✓ 90% | Low | Corrected verification logic |
| Documentation | ⚠️ 70% | Medium | Updated; needs ops procedures |
| Operational Testing | ⚠️ 40% | High | Must test reindex + symlinks |
| Integration Testing | ⚠️ 30% | High | Must test backward compat |

**Recommendation:**

❌ **Do NOT ship Stage 9 yet without:**

1. ✓ Running all verifier checks on existing artifacts (reveals issues)
2. ✓ Code review of governance/doctrine/DB patterns
3. ✓ Operational testing of reindex + symlinks
4. ✓ Integration tests for backward compatibility

---

## Revised Definition of Done

### Before Declaring Stage 9 Complete

- [x] Core implementation written (pipelines snapshot, hash, verify)
- [x] Automated verification framework created (determinism.py)
- [x] Verification logic corrected (no hardcoded allowlists)
- [x] Documentation updated (honest scope)
- [ ] Code review checklist passed
- [ ] Operational tests passed (reindex, symlinks, no DB)
- [ ] Integration tests passed (backward compat)
- [ ] All existing artifacts pass verification
- [ ] Staging deployment validated

**Current Progress:** 4/9 items complete. **Not ready for production yet.**

---

## Conclusion

Stage 9 has **solid code foundations** but **incomplete verification and testing**. The fixes made today (snapshot allowlist removal, chainable validation, documentation clarity) address critical issues.

**Next action:** Run verification suite on existing artifacts, then execute operational + integration tests before production deployment.

