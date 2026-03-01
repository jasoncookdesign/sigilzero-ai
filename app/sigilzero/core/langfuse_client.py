"""
Langfuse Observability Client: Phase 1.0 Determinism-Preserving Tracing

This module provides observability via Langfuse while preserving all Phase 1.0
determinism invariants:

1. Trace IDs are EXCLUDED from determinism (like timestamps)
2. Tracing is OPTIONAL (system works without Langfuse)
3. Traces LINK TO run_id but don't participate in inputs_hash
4. Tracing failures are SILENT (don't break execution)
5. Trace metadata includes governance identifiers (job_id, run_id)

Critical Principle:
- Observability is SECONDARY to execution
- run_id is derived BEFORE tracing starts
- Trace data never affects canonical snapshots or hashes
- System degrades gracefully if Langfuse unavailable
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Callable
from functools import wraps
from contextlib import contextmanager

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover
    Langfuse = None  # type: ignore


class _NoOpSpan:
    """No-op span for when Langfuse is not enabled."""

    def end(self, **kwargs):
        pass

    def update(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTrace:
    """No-op trace for when Langfuse is not enabled."""

    def __init__(self, name: str):
        self.name = name
        self.id = None

    def end(self, **kwargs):
        pass

    def update(self, **kwargs):
        pass

    def span(self, name: str, **kwargs):
        return _NoOpSpan()


class LangfuseClient:
    """Thin wrapper for Langfuse tracing.
    
    Phase 1.0 Guarantees:
    - Tracing is optional (enabled flag)
    - All operations wrapped in try/except (silent failures)
    - No-op implementations when disabled
    - Trace IDs never participate in determinism
    """

    def __init__(self) -> None:
        self.enabled = bool(
            os.getenv("LANGFUSE_PUBLIC_KEY") 
            and os.getenv("LANGFUSE_SECRET_KEY") 
            and os.getenv("LANGFUSE_HOST")
        )
        if self.enabled and Langfuse is not None:
            try:
                self._client = Langfuse(
                    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                    host=os.getenv("LANGFUSE_HOST"),
                )
            except Exception:
                self._client = None
                self.enabled = False
        else:
            self._client = None

    def trace(
        self, 
        name: str, 
        input: Optional[Dict[str, Any]] = None, 
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ):
        """Start a trace with given name, input, and metadata.
        
        Args:
            name: Trace name (e.g., "job:instagram_copy")
            input: Input data (should NOT include canonical snapshots)
            metadata: Metadata (job_id, run_id, brand, etc.)
            user_id: User identifier (optional)
            session_id: Session identifier (optional)
            tags: List of tags for filtering (e.g., ["instagram", "production"])
        
        Returns:
            Trace object (or no-op if disabled/failed)
        
        Phase 1.0: Trace creation NEVER affects run_id or inputs_hash.
        """
        if not self._client:
            return _NoOpTrace(name=name)
        try:
            return self._client.trace(
                name=name,
                input=input,
                metadata=metadata or {},
                user_id=user_id,
                session_id=session_id,
                tags=tags,
            )
        except Exception:
            return _NoOpTrace(name=name)

    def span(
        self, 
        trace_id: Optional[str], 
        name: str, 
        input: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Start a span within a trace.
        
        Args:
            trace_id: Parent trace ID
            name: Span name (e.g., "load_doctrine", "generate_caption")
            input: Input data for this span
            metadata: Span-specific metadata
        
        Returns:
            Span object (or no-op if disabled/failed)
        """
        if not self._client or not trace_id:
            return _NoOpSpan()
        try:
            return self._client.span(
                trace_id=trace_id,
                name=name,
                input=input,
                metadata=metadata or {},
            )
        except Exception:
            return _NoOpSpan()

    def generation(
        self,
        trace_id: Optional[str],
        name: str,
        model: str,
        input: Any = None,
        output: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        usage: Optional[Dict[str, int]] = None,
    ):
        """Record an LLM generation event.
        
        Args:
            trace_id: Parent trace ID
            name: Generation name (e.g., "caption_generation")
            model: Model identifier (e.g., "gpt-4")
            input: Prompt/messages sent to model
            output: Model response
            metadata: Generation metadata
            usage: Token usage (prompt_tokens, completion_tokens, total_tokens)
        
        Returns:
            Generation object (or no-op if disabled/failed)
        """
        if not self._client or not trace_id:
            return _NoOpSpan()
        try:
            return self._client.generation(
                trace_id=trace_id,
                name=name,
                model=model,
                input=input,
                output=output,
                metadata=metadata or {},
                usage=usage,
            )
        except Exception:
            return _NoOpSpan()

    @contextmanager
    def trace_context(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
    ):
        """Context manager for tracing a code block.
        
        Usage:
            with lf.trace_context("process_job", metadata={"job_id": "abc"}):
                # ... code to trace ...
                pass
        
        Yields:
            Trace object (or no-op if disabled)
        """
        trace = self.trace(name=name, metadata=metadata, tags=tags)
        try:
            yield trace
        finally:
            trace.end()

    @contextmanager
    def span_context(
        self,
        trace_id: Optional[str],
        name: str,
        input: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Context manager for a span within a trace.
        
        Usage:
            with lf.span_context(trace_id, "load_context", metadata={"files": 5}):
                # ... code to trace ...
                pass
        
        Yields:
            Span object (or no-op if disabled)
        """
        span = self.span(trace_id=trace_id, name=name, input=input, metadata=metadata)
        try:
            yield span
        finally:
            span.end()


_langfuse_client: Optional[LangfuseClient] = None


def get_langfuse() -> Optional[LangfuseClient]:
    """Get or create the global Langfuse client.
    
    Returns:
        LangfuseClient if enabled, None otherwise
    
    Phase 1.0: Returns None if Langfuse not configured (degraded mode).
    """
    global _langfuse_client
    if _langfuse_client is None:
        _langfuse_client = LangfuseClient()
    return _langfuse_client if _langfuse_client.enabled else None


def trace_function(
    name: Optional[str] = None,
    capture_args: bool = False,
    capture_result: bool = False,
):
    """Decorator to trace function execution.
    
    Args:
        name: Trace name (default: function name)
        capture_args: Include function args in trace input
        capture_result: Include function result in trace output
    
    Usage:
        @trace_function(name="generate_caption", capture_result=True)
        def generate_caption(prompt: str) -> str:
            return call_openai(prompt)
    
    Phase 1.0: Tracing failures are SILENT (don't break function execution).
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            lf = get_langfuse()
            if lf is None:
                return func(*args, **kwargs)
            
            trace_name = name or func.__name__
            input_data = None
            if capture_args:
                input_data = {"args": str(args), "kwargs": str(kwargs)}
            
            trace = lf.trace(name=trace_name, input=input_data)
            try:
                result = func(*args, **kwargs)
                if capture_result:
                    trace.update(output={"result": str(result)})
                return result
            except Exception as e:
                trace.update(output={"error": str(e)}, level="ERROR")
                raise
            finally:
                trace.end()
        
        return wrapper
    return decorator

