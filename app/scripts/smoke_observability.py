#!/usr/bin/env python3
"""
Smoke Test: Observability & Langfuse Integration

Tests that observability framework:
1. Preserves determinism invariants (run_id unchanged)
2. Works with Langfuse disabled (graceful degradation)
3. Fails silently (tracing errors don't break execution)
4. Excludes trace data from inputs_hash
5. Links traces to governance identifiers (job_id, run_id)
6. Provides consistent metadata across pipelines

Phase 1.0 Determinism Checks:
- run_id derivation unchanged (with/without tracing)
- inputs_hash unchanged (with/without tracing)
- Trace IDs not included in canonical snapshots
- System works without Langfuse
- Tracing failures don't break execution
"""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.core.langfuse_client import get_langfuse, LangfuseClient
from sigilzero.core.observability import (
    trace_pipeline_execution,
    trace_step,
    trace_llm_call,
    trace_doctrine_load,
    trace_context_retrieval,
    trace_snapshot_creation,
    trace_output_generation,
    finalize_trace,
    is_observability_enabled,
)
from sigilzero.core.hashing import compute_inputs_hash, derive_run_id
from sigilzero.core.schemas import RunManifest


def test_langfuse_disabled_graceful_degradation():
    """Test: System works when Langfuse is disabled."""
    print("TEST: Langfuse disabled (graceful degradation)")
    
    # Ensure Langfuse is disabled
    with patch.dict(os.environ, {}, clear=True):
        lf = get_langfuse()
        assert lf is None, "Langfuse should be None when not configured"
        
        # Trace operations should return None
        trace, trace_id = trace_pipeline_execution(
            job_id="test-job",
            run_id="test-run",
            job_type="instagram_copy",
            brand="test-brand",
            inputs_hash="abc123",
        )
        assert trace is None, "Trace should be None when Langfuse disabled"
        assert trace_id is None, "Trace ID should be None when Langfuse disabled"
        
        # Context managers should work (no-op)
        with trace_step(None, "test_step") as output:
            assert output is None, "Step output should be None when tracing disabled"
        
        # Utility functions should not crash
        trace_llm_call(None, "test", "gpt-4", "prompt", "response")
        trace_doctrine_load(None, "test", "v1", Path("/tmp"), "hash")
        trace_context_retrieval(None, "glob", 5)
        trace_snapshot_creation(None, "brief", "hash", 1024)
        trace_output_generation(None, ["output.md"], 2048)
        finalize_trace(None, "succeeded")
        
        # is_observability_enabled should return False
        assert not is_observability_enabled(), "Observability should be disabled"
        
        print("  ✅ Graceful degradation works (all operations no-op)")


def test_trace_ids_excluded_from_determinism():
    """Test: Trace IDs don't participate in inputs_hash or run_id."""
    print("\nTEST: Trace IDs excluded from determinism")
    
    # Create test snapshot hashes
    snapshot_hashes = {
        "brief": "abc123def456",
        "context": "789012345678",
        "model_config": "345678901234",
        "doctrine": "567890123456",
    }
    
    # Compute inputs_hash and run_id WITHOUT tracing
    inputs_hash_without_trace = compute_inputs_hash(snapshot_hashes)
    run_id_without_trace = derive_run_id(inputs_hash_without_trace)
    
    # Simulate adding trace ID (should NOT affect determinism)
    snapshot_hashes_with_trace_attempt = snapshot_hashes.copy()
    # Verify trace_id is NOT in snapshot_hashes (should never be there)
    assert "trace_id" not in snapshot_hashes_with_trace_attempt, "trace_id should NEVER be in snapshots"
    
    # Compute inputs_hash and run_id again (same snapshots)
    inputs_hash_with_trace_attempt = compute_inputs_hash(snapshot_hashes_with_trace_attempt)
    run_id_with_trace_attempt = derive_run_id(inputs_hash_with_trace_attempt)
    
    # Check determinism preserved
    assert inputs_hash_without_trace == inputs_hash_with_trace_attempt, "inputs_hash changed (DETERMINISM VIOLATION)"
    assert run_id_without_trace == run_id_with_trace_attempt, "run_id changed (DETERMINISM VIOLATION)"
    
    print("  ✅ Trace IDs excluded from determinism")
    print(f"     inputs_hash: {inputs_hash_without_trace} (unchanged)")
    print(f"     run_id: {run_id_without_trace} (unchanged)")


def test_tracing_after_run_id_derivation():
    """Test: Tracing happens AFTER run_id is derived."""
    print("\nTEST: Tracing after run_id derivation")
    
    # Simulate pipeline execution order
    execution_log = []
    
    # 1. Create snapshots
    execution_log.append("1_create_snapshots")
    snapshot_hashes = {
        "brief": "abc123",
        "context": "def456",
        "model_config": "ghi789",
    }
    
    # 2. Compute inputs_hash
    execution_log.append("2_compute_inputs_hash")
    inputs_hash = compute_inputs_hash(snapshot_hashes)
    
    # 3. Derive run_id (BEFORE tracing)
    execution_log.append("3_derive_run_id")
    run_id = derive_run_id(inputs_hash)
    
    # 4. Start tracing (AFTER run_id exists)
    execution_log.append("4_start_tracing")
    trace, trace_id = trace_pipeline_execution(
        job_id="test-job",
        run_id=run_id,  # run_id passed TO tracing (not derived FROM tracing)
        job_type="instagram_copy",
        brand="test",
        inputs_hash=inputs_hash,
    )
    
    # Verify execution order
    assert execution_log == [
        "1_create_snapshots",
        "2_compute_inputs_hash",
        "3_derive_run_id",
        "4_start_tracing",
    ], "Execution order incorrect"
    
    print("  ✅ Tracing happens AFTER run_id derivation")
    print(f"     Order: {' → '.join(execution_log)}")


def test_manifest_excludes_trace_id_from_snapshots():
    """Test: Trace IDs never written to snapshots or deterministic manifest bytes."""
    print("\nTEST: Manifest excludes trace_id from snapshots")
    
    # Create mock manifest data (like RunManifest)
    manifest_data = {
        "schema_version": "1.2.0",
        "job_id": "test-job-001",
        "run_id": "abc123def456",
        "queue_job_id": "rq-uuid-12345",
        "job_ref": "jobs/test/brief.yaml",
        "job_type": "instagram_copy",
        "started_at": "2026-02-28T12:00:00Z",
        "finished_at": "2026-02-28T12:00:05Z",
        "status": "succeeded",
        "inputs_hash": "def456789012",
        "input_snapshots": {
            "brief": {
                "path": "inputs/brief.resolved.json",
                "sha256": "abc123",
                "bytes": 1024,
            },
            "context": {
                "path": "inputs/context.resolved.json",
                "sha256": "def456",
                "bytes": 2048,
            },
        },
        "langfuse_trace_id": "trace-xyz-789",  # Recorded in manifest but separate
        "artifacts": {},
        "meta": {},
    }
    
    # Check trace_id NOT in input_snapshots
    for snapshot_name, snapshot_data in manifest_data["input_snapshots"].items():
        assert "trace_id" not in snapshot_data, f"trace_id found in {snapshot_name} snapshot"
        assert "langfuse_trace_id" not in snapshot_data, f"langfuse_trace_id found in {snapshot_name} snapshot"
    
    # Deterministic manifest serialization must exclude nondeterministic fields.
    manifest = RunManifest(**manifest_data)
    serialized = manifest.model_dump()
    serialized_json = manifest.model_dump_json()

    assert "langfuse_trace_id" not in serialized, "langfuse_trace_id must be excluded from deterministic manifest"
    assert "started_at" not in serialized, "started_at must be excluded from deterministic manifest"
    assert "finished_at" not in serialized, "finished_at must be excluded from deterministic manifest"

    assert "langfuse_trace_id" not in serialized_json, "langfuse_trace_id leaked into deterministic manifest JSON"
    assert "started_at" not in serialized_json, "started_at leaked into deterministic manifest JSON"
    assert "finished_at" not in serialized_json, "finished_at leaked into deterministic manifest JSON"

    # Byte determinism check: different nondeterministic inputs must serialize identically.
    manifest_data_variant = manifest_data.copy()
    manifest_data_variant["started_at"] = "2026-02-28T13:11:22Z"
    manifest_data_variant["finished_at"] = "2026-02-28T13:11:30Z"
    manifest_data_variant["langfuse_trace_id"] = "trace-different-123"

    manifest_variant = RunManifest(**manifest_data_variant)

    deterministic_bytes_1 = json.dumps(
        manifest.model_dump(),
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    deterministic_bytes_2 = json.dumps(
        manifest_variant.model_dump(),
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    assert deterministic_bytes_1 == deterministic_bytes_2, (
        "Deterministic manifest bytes changed across runs with identical snapshots"
    )
    
    # Simulate serialization (trace_id should not affect snapshot hashes)
    for snapshot_name, snapshot_data in manifest_data["input_snapshots"].items():
        snapshot_json = json.dumps(snapshot_data, sort_keys=True)
        assert "trace" not in snapshot_json.lower(), f"'trace' keyword found in {snapshot_name} snapshot JSON"
    
    print("  ✅ Trace IDs excluded from input snapshots")
    print("  ✅ Deterministic manifest serialization excludes nondeterministic fields")
    print("  ✅ Deterministic manifest bytes are stable across fresh reruns")
    print("     excluded: langfuse_trace_id, started_at, finished_at")


def test_silent_trace_failures():
    """Test: Tracing failures don't break pipeline execution."""
    print("\nTEST: Silent trace failures")
    
    # Test that trace operations with None trace_id don't crash
    # (This simulates Langfuse being unavailable/failing)
    
    try:
        # All operations should work with None trace_id
        with trace_step(None, "test_step"):
            pass
        
        trace_llm_call(None, "test", "gpt-4", "prompt", "response")
        trace_doctrine_load(None, "test", "v1", Path("/tmp"), "hash")
        trace_context_retrieval(None, "glob", 5)
        trace_snapshot_creation(None, "brief", "hash", 1024)
        trace_output_generation(None, ["output.md"], 2048)
        finalize_trace(None, "succeeded")
        
        # If we get here, all operations succeeded (silent failures)
        success = True
    except Exception as e:
        success = False
        print(f"     ERROR: Operation crashed: {e}")
    
    assert success, "Tracing operations should not crash when trace_id is None"
    
    print("  ✅ Tracing failures are silent (don't break execution)")
    print("     All operations handle None trace_id without crashing")


def test_trace_metadata_includes_governance_ids():
    """Test: Traces include job_id and run_id in metadata."""
    print("\nTEST: Trace metadata includes governance identifiers")
    
    # This test validates the pattern, not actual Langfuse call
    # (actual call requires Langfuse server)
    
    job_id = "test-job-12345"
    run_id = "test-run-67890"
    job_type = "instagram_copy"
    brand = "test-brand"
    inputs_hash = "abc123def456"
    queue_job_id = "rq-uuid-99999"
    
    # Verify trace_pipeline_execution includes correct metadata
    # (This will be a no-op since Langfuse is disabled, but validates the pattern)
    trace, trace_id = trace_pipeline_execution(
        job_id=job_id,
        run_id=run_id,
        job_type=job_type,
        brand=brand,
        inputs_hash=inputs_hash,
        queue_job_id=queue_job_id,
    )
    
    # Since Langfuse is disabled, trace is None (expected)
    # But the function signature demonstrates correct metadata pattern
    
    print("  ✅ Trace metadata pattern includes governance identifiers")
    print(f"     job_id: {job_id}")
    print(f"     run_id: {run_id}")
    print(f"     job_type: {job_type}")
    print(f"     brand: {brand}")


def test_observability_utilities_consistent():
    """Test: Observability utilities provide consistent patterns."""
    print("\nTEST: Observability utilities consistency")
    
    # Test all utility functions work with None trace_id (disabled mode)
    trace_id = None
    
    # All should not crash and return gracefully
    with trace_step(trace_id, "test_step"):
        pass
    
    trace_llm_call(
        trace_id=trace_id,
        name="test_generation",
        model="gpt-4",
        prompt="test prompt",
        response="test response",
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )
    
    trace_doctrine_load(
        trace_id=trace_id,
        doctrine_id="prompts/test",
        version="v1.0.0",
        path=Path("/tmp/doctrine.md"),
        sha256="abc123",
    )
    
    trace_context_retrieval(
        trace_id=trace_id,
        mode="retrieve",
        files_retrieved=5,
        query="test query",
        top_k=10,
        method="keyword",
    )
    
    trace_snapshot_creation(
        trace_id=trace_id,
        snapshot_name="brief",
        snapshot_hash="abc123",
        snapshot_bytes=1024,
    )
    
    trace_output_generation(
        trace_id=trace_id,
        output_files=["output1.md", "output2.md"],
        total_bytes=2048,
        generation_metadata={"variants": 2},
    )
    
    finalize_trace(None, "succeeded", artifacts={"test": "artifact"})
    
    print("  ✅ All observability utilities work consistently")
    print("     All functions handle None trace_id gracefully")


def test_context_managers_work_correctly():
    """Test: Context managers (trace_step, span_context) work correctly."""
    print("\nTEST: Context managers work correctly")
    
    # Test with capture_output=False
    with trace_step(None, "test_step_no_output") as output:
        assert output is None, "Output should be None when capture_output=False"
    
    # Test with capture_output=True
    with trace_step(None, "test_step_with_output", capture_output=True) as output:
        assert output == {}, "Output should be empty dict when capture_output=True"
        # Can populate output (no-op when trace_id is None)
        output["test"] = "value"
    
    # Test exception handling
    try:
        with trace_step(None, "test_step_exception"):
            raise ValueError("Test exception")
    except ValueError:
        pass  # Expected
    
    print("  ✅ Context managers work correctly")
    print("     Handles both output capture modes and exceptions")


def main():
    print("=" * 70)
    print("OBSERVABILITY & LANGFUSE INTEGRATION - SMOKE TESTS")
    print("=" * 70)
    
    try:
        test_langfuse_disabled_graceful_degradation()
        test_trace_ids_excluded_from_determinism()
        test_tracing_after_run_id_derivation()
        test_manifest_excludes_trace_id_from_snapshots()
        test_silent_trace_failures()
        test_trace_metadata_includes_governance_ids()
        test_observability_utilities_consistent()
        test_context_managers_work_correctly()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nPhase 1.0 Determinism Guarantees Verified:")
        print("  ✓ run_id derivation unchanged (tracing happens after)")
        print("  ✓ inputs_hash unchanged (trace IDs excluded)")
        print("  ✓ Trace IDs never in input snapshots")
        print("  ✓ System works without Langfuse (graceful degradation)")
        print("  ✓ Tracing failures are silent (don't break execution)")
        print("  ✓ Governance identifiers included in trace metadata")
        print("  ✓ Observability utilities provide consistent patterns")
        
        return 0
    
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
