from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover
    Langfuse = None  # type: ignore


class _NoOpSpan:
    """No-op span for when Langfuse is not enabled."""

    def end(self, **kwargs):
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


class LangfuseClient:
    """Thin wrapper for Langfuse tracing."""

    def __init__(self) -> None:
        self.enabled = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_HOST"))
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

    def trace(self, name: str, input: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None):
        """Start a trace with given name, input, and metadata."""
        if not self._client:
            return _NoOpTrace(name=name)
        try:
            return self._client.trace(name=name, input=input, metadata=metadata or {})
        except Exception:
            return _NoOpTrace(name=name)

    def span(self, trace_id: Optional[str], name: str, input: Any = None):
        """Start a span within a trace."""
        if not self._client or not trace_id:
            return _NoOpSpan()
        try:
            return self._client.span(trace_id=trace_id, name=name, input=input)
        except Exception:
            return _NoOpSpan()


_langfuse_client: Optional[LangfuseClient] = None


def get_langfuse() -> Optional[LangfuseClient]:
    """Get or create the global Langfuse client."""
    global _langfuse_client
    if _langfuse_client is None:
        _langfuse_client = LangfuseClient()
    return _langfuse_client if _langfuse_client.enabled else None
