"""
Observability Utilities: Phase 1.0 Determinism-Preserving Tracing Patterns

This module provides standardized observability patterns for SIGIL.ZERO pipelines
while preserving all Phase 1.0 determinism invariants.

Key Principles:
1. Observability is OPTIONAL (system works without Langfuse)
2. Trace IDs EXCLUDED from determinism (like timestamps)
3. Tracing happens AFTER run_id derivation (never affects inputs_hash)
4. Silent failures (tracing errors don't break execution)
5. Consistent metadata (job_id, run_id, brand for all traces)

Usage Patterns:
- trace_pipeline_execution(): Top-level pipeline tracing
- trace_llm_call(): Instrument OpenAI/LLM calls
- trace_doctrine_load(): Instrument doctrine loading
- trace_context_retrieval(): Instrument context retrieval
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Callable
from contextlib import contextmanager
from pathlib import Path

from .langfuse_client import get_langfuse


def trace_pipeline_execution(
    job_id: str,
    run_id: str,
    job_type: str,
    brand: str,
    inputs_hash: str,
    queue_job_id: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str]]:
    """Start tracing for a pipeline execution (top-level trace).
    
    Args:
        job_id: Governance job identifier
        run_id: Deterministic run identifier
        job_type: Pipeline type (e.g., "instagram_copy")
        brand: Brand name
        inputs_hash: Hash of all input snapshots
        queue_job_id: RQ queue job UUID (optional)
    
    Returns:
        (trace_object, trace_id) tuple; (None, None) if tracing disabled
    
    Phase 1.0: Called AFTER run_id is derived (never affects determinism).
    Trace metadata includes governance identifiers but trace itself is excluded from hashing.
    
    Usage:
        trace, trace_id = trace_pipeline_execution(
            job_id=brief.job_id,
            run_id=run_id,
            job_type=brief.job_type,
            brand=brief.brand,
            inputs_hash=inputs_hash,
            queue_job_id=queue_job_id,
        )
        
        # Use trace_id for subsequent spans
        with trace_step(trace_id, "generate_captions"):
            ...
    """
    lf = get_langfuse()
    if lf is None:
        return None, None
    
    trace = lf.trace(
        name=f"job:{job_type}",
        input={
            "job_id": job_id,
            "run_id": run_id,
            "inputs_hash": inputs_hash,
        },
        metadata={
            "job_id": job_id,
            "run_id": run_id,
            "job_type": job_type,
            "brand": brand,
            "queue_job_id": queue_job_id,
            "stage": "pipeline_execution",
        },
        tags=[job_type, brand],
    )
    
    return trace, trace.id


@contextmanager
def trace_step(
    trace_id: Optional[str],
    step_name: str,
    metadata: Optional[Dict[str, Any]] = None,
    capture_output: bool = False,
):
    """Context manager for tracing a pipeline step (span).
    
    Args:
        trace_id: Parent trace ID
        step_name: Name of the step (e.g., "load_doctrine", "generate_captions")
        metadata: Step-specific metadata
        capture_output: If True, yields a dict to populate with output
    
    Yields:
        Either None or a dict for output data (if capture_output=True)
    
    Usage:
        with trace_step(trace_id, "load_context", metadata={"corpus_size": 500}):
            context = load_context()
        
        # With output capture:
        with trace_step(trace_id, "generate", capture_output=True) as output:
            result = generate_caption()
            if output is not None:
                output["caption"] = result
    """
    lf = get_langfuse()
    if lf is None or trace_id is None:
        yield {} if capture_output else None
        return
    
    output_data = {} if capture_output else None
    
    with lf.span_context(trace_id, step_name, metadata=metadata) as span:
        try:
            yield output_data
            if output_data:
                span.update(output=output_data)
        except Exception as e:
            span.update(output={"error": str(e)}, level="ERROR")
            raise


def trace_llm_call(
    trace_id: Optional[str],
    name: str,
    model: str,
    prompt: str,
    response: str,
    usage: Optional[Dict[str, int]] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Record an LLM generation event.
    
    Args:
        trace_id: Parent trace ID
        name: Generation name (e.g., "caption_generation")
        model: Model identifier (e.g., "gpt-4", "gpt-3.5-turbo")
        prompt: Prompt sent to model
        response: Model response
        usage: Token usage dict (prompt_tokens, completion_tokens, total_tokens)
        metadata: Additional metadata (temperature, max_tokens, etc.)
    
    Phase 1.0: LLM call results are stored in output files (deterministic).
    This trace is for observability only (performance, usage, debugging).
    
    Usage:
        trace_llm_call(
            trace_id=trace_id,
            name="caption_generation",
            model="gpt-4",
            prompt=rendered_prompt,
            response=completion.choices[0].message.content,
            usage={
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            },
            metadata={"temperature": 0.7, "max_tokens": 500},
        )
    """
    lf = get_langfuse()
    if lf is None or trace_id is None:
        return
    
    lf.generation(
        trace_id=trace_id,
        name=name,
        model=model,
        input={"prompt": prompt},
        output={"response": response},
        usage=usage,
        metadata=metadata or {},
    )


def trace_doctrine_load(
    trace_id: Optional[str],
    doctrine_id: str,
    version: str,
    path: Path,
    sha256: str,
):
    """Record doctrine loading event.
    
    Args:
        trace_id: Parent trace ID
        doctrine_id: Doctrine identifier (e.g., "prompts/instagram_copy")
        version: Doctrine version (e.g., "v1.0.0")
        path: Path where doctrine was loaded from
        sha256: Hash of doctrine content
    
    Phase 1.0: Doctrine hash participates in inputs_hash (determinism).
    This trace is for observability only (which version was used, when).
    
    Usage:
        with trace_step(trace_id, "load_doctrine") as step:
            doctrine = load_doctrine(doctrine_id, version)
            trace_doctrine_load(
                trace_id=trace_id,
                doctrine_id=doctrine_id,
                version=version,
                path=doctrine_path,
                sha256=doctrine_hash,
            )
    """
    lf = get_langfuse()
    if lf is None or trace_id is None:
        return
    
    with lf.span_context(
        trace_id=trace_id,
        name="load_doctrine",
        input={"doctrine_id": doctrine_id, "version": version},
        metadata={
            "doctrine_id": doctrine_id,
            "version": version,
            "path": str(path),
            "sha256": sha256,
            "stage": "doctrine_resolution",
        },
    ):
        pass  # Span ends automatically


def trace_context_retrieval(
    trace_id: Optional[str],
    mode: str,
    files_retrieved: int,
    query: Optional[str] = None,
    top_k: Optional[int] = None,
    method: Optional[str] = None,
):
    """Record context retrieval event.
    
    Args:
        trace_id: Parent trace ID
        mode: Context mode ("glob" or "retrieve")
        files_retrieved: Number of files retrieved
        query: Query string (for retrieve mode)
        top_k: Max items to retrieve (for retrieve mode)
        method: Retrieval method ("keyword", etc.)
    
    Phase 1.0: Context files participate in inputs_hash (determinism).
    This trace is for observability only (how many files, which method).
    
    Usage:
        with trace_step(trace_id, "load_context"):
            context = load_context_retrieval(query=brief.context_query, top_k=10)
            trace_context_retrieval(
                trace_id=trace_id,
                mode="retrieve",
                files_retrieved=len(context),
                query=brief.context_query,
                top_k=10,
                method="keyword",
            )
    """
    lf = get_langfuse()
    if lf is None or trace_id is None:
        return
    
    with lf.span_context(
        trace_id=trace_id,
        name="context_retrieval",
        input={"mode": mode, "query": query, "top_k": top_k},
        metadata={
            "mode": mode,
            "files_retrieved": files_retrieved,
            "query": query,
            "top_k": top_k,
            "method": method,
            "stage": "context_loading",
        },
    ) as span:
        span.update(output={"files_retrieved": files_retrieved})


def trace_snapshot_creation(
    trace_id: Optional[str],
    snapshot_name: str,
    snapshot_hash: str,
    snapshot_bytes: int,
):
    """Record snapshot creation event.
    
    Args:
        trace_id: Parent trace ID
        snapshot_name: Name of snapshot (e.g., "brief", "context", "doctrine")
        snapshot_hash: SHA256 hash of snapshot content
        snapshot_bytes: Size of snapshot in bytes
    
    Phase 1.0: Snapshots are canonical inputs (determinism).
    This trace is for observability only (snapshot sizes, hashes).
    
    Usage:
        for name, snapshot in input_snapshots.items():
            trace_snapshot_creation(
                trace_id=trace_id,
                snapshot_name=name,
                snapshot_hash=snapshot.sha256,
                snapshot_bytes=snapshot.bytes,
            )
    """
    lf = get_langfuse()
    if lf is None or trace_id is None:
        return
    
    with lf.span_context(
        trace_id=trace_id,
        name=f"snapshot:{snapshot_name}",
        metadata={
            "snapshot_name": snapshot_name,
            "sha256": snapshot_hash,
            "bytes": snapshot_bytes,
            "stage": "snapshot_creation",
        },
    ):
        pass  # Span ends automatically


def trace_output_generation(
    trace_id: Optional[str],
    output_files: list[str],
    total_bytes: int,
    generation_metadata: Optional[Dict[str, Any]] = None,
):
    """Record output generation event.
    
    Args:
        trace_id: Parent trace ID
        output_files: List of output file names
        total_bytes: Total size of all outputs
        generation_metadata: Metadata from generation (variants, formats, etc.)
    
    Phase 1.0: Output files are stored in outputs/ directory (deterministic).
    This trace is for observability only (output sizes, file counts).
    
    Usage:
        with trace_step(trace_id, "generate_outputs"):
            outputs = generate_captions()
            trace_output_generation(
                trace_id=trace_id,
                output_files=list(outputs.keys()),
                total_bytes=sum(len(v) for v in outputs.values()),
                generation_metadata={"variants": 5, "format": "markdown"},
            )
    """
    lf = get_langfuse()
    if lf is None or trace_id is None:
        return
    
    with lf.span_context(
        trace_id=trace_id,
        name="output_generation",
        metadata={
            "output_count": len(output_files),
            "total_bytes": total_bytes,
            "generation_metadata": generation_metadata or {},
            "stage": "output_generation",
        },
    ) as span:
        span.update(output={
            "files": output_files,
            "total_bytes": total_bytes,
        })


def finalize_trace(
    trace: Optional[Any],
    status: str,
    error: Optional[str] = None,
    artifacts: Optional[Dict[str, Any]] = None,
):
    """Finalize a trace with final status and artifacts.
    
    Args:
        trace: Trace object from trace_pipeline_execution()
        status: Final status ("succeeded", "failed")
        error: Error message (if failed)
        artifacts: Output artifacts metadata (file paths, sizes)
    
    Phase 1.0: Called at end of pipeline execution.
    Trace is finalized with success/failure status for observability.
    
    Usage:
        try:
            # ... pipeline execution ...
            finalize_trace(trace, "succeeded", artifacts=manifest.artifacts)
        except Exception as e:
            finalize_trace(trace, "failed", error=str(e))
            raise
    """
    if trace is None:
        return
    
    try:
        trace.update(
            output={
                "status": status,
                "error": error,
                "artifacts": artifacts or {},
            },
            level="ERROR" if status == "failed" else "DEFAULT",
        )
        trace.end()
    except Exception:
        pass  # Silent failure (don't break execution)


# Convenience function for checking if observability is enabled
def is_observability_enabled() -> bool:
    """Check if Langfuse observability is enabled.
    
    Returns:
        True if Langfuse configured and available, False otherwise
    
    Usage:
        if is_observability_enabled():
            # ... add extra observability instrumentation ...
            pass
    """
    lf = get_langfuse()
    return lf is not None
