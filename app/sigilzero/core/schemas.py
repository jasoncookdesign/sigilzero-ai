from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


# Shared models
class IGControlBlock(BaseModel):
    """Instagram generation control block."""
    caption_count: int = Field(default=5)
    hashtag_count: int = Field(default=12)
    max_caption_chars: int = Field(default=800)
    include_cta: bool = Field(default=True)
    include_emojis: bool = Field(default=False)


class BriefBlock(BaseModel):
    """Generic input block for brief."""
    name: str
    kind: str = Field(default="markdown")
    content: str


# -----------------------------
# Phase 0: Job briefs + runs
# -----------------------------

class BriefSpec(BaseModel):
    schema_version: str = Field(default="1.0.0")
    job_id: str
    job_type: str = Field(default="instagram_copy")
    brand: str

    # Optional, to keep Phase 0 generic
    artist: Optional[str] = None
    title: Optional[str] = None

    # Light structure for copy control
    tone_tags: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)

    # Instagram-specific config for Phase 0
    ig: IGControlBlock = Field(default_factory=IGControlBlock)

    # Input blocks (e.g. "post_context", "notes", etc.)
    blocks: List[BriefBlock] = Field(default_factory=list)

    # Freeform input blocks (legacy; kept for compatibility)
    inputs: Dict[str, str] = Field(default_factory=dict)
    
    # Internal fields
    brief_hash: Optional[str] = None
    repo_commit: Optional[str] = None


class JobRunRequest(BaseModel):
    job_ref: str
    params: Dict[str, Any] = Field(default_factory=dict)


class JobRunResponse(BaseModel):
    job_id: str
    run_id: Optional[str] = None


# -----------------------------
# Corpus selection + context pack
# -----------------------------

class FileSelector(BaseModel):
    """
    Declarative selection for context loading.
    All paths are relative to repo root unless absolute.
    """
    root: str = Field(default="corpus")
    include_globs: List[str] = Field(default_factory=lambda: ["**/*.md", "**/*.txt"])
    exclude_globs: List[str] = Field(default_factory=list)
    max_files: int = Field(default=200)
    max_total_bytes: int = Field(default=2_000_000)  # 2 MB safety cap


class ContextSelector(BaseModel):
    """Selector for including files in context via globs."""
    root: str = Field(default="corpus")
    include_globs: List[str] = Field(default_factory=list)
    exclude_globs: List[str] = Field(default_factory=list)
    max_files: int = Field(default=200)


class ContextSpec(BaseModel):
    """
    Describes how to build a context pack for an execution.
    Job-centric for Phase 0; avoids release_ref.
    """
    schema_version: str = Field(default="1.0.0")
    job_ref: Optional[str] = None
    job_type: Optional[str] = None
    brand: Optional[str] = None
    
    # Selectors for including files
    selectors: List[ContextSelector] = Field(default_factory=list)
    
    # Optional context spec metadata
    context_spec_hash: Optional[str] = None
    repo_commit: Optional[str] = None


class ContextItemSpan(BaseModel):
    start_line: Optional[int] = None
    end_line: Optional[int] = None


class ContextItem(BaseModel):
    kind: Literal["corpus", "job", "artifact", "other"] = "other"
    path: str
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None
    media_type: Optional[str] = Field(default="text/plain")
    span: Optional[ContextItemSpan] = None
    content: Optional[str] = None


class ContextPack(BaseModel):
    spec: ContextSpec
    items: List[ContextItem] = Field(default_factory=list)

    def as_prompt_block(self) -> str:
        """Simple concatenation format for Phase 0."""
        parts: List[str] = []
        for it in self.items:
            if not it.content:
                continue
            header = f"# {it.kind}: {it.path}"
            parts.append(header)
            parts.append(it.content.strip())
            parts.append("\n")
        return "\n".join(parts).strip()


# -----------------------------
# Generation + LLM configuration
# -----------------------------

class GenerationSpec(BaseModel):
    """Specification for LLM generation."""
    provider: str = Field(default="openai")
    model: str = Field(default="gpt-4-turbo")
    temperature: float = Field(default=0.3)
    top_p: float = Field(default=1.0)
    
    # Prompt template info
    prompt_template: str
    prompt_template_version: str = Field(default="1.0.0")
    
    # Context and response schema
    context_content_hash: str
    response_schema: str
    response_schema_version: str = Field(default="1.0.0")
    
    # Cache and generation metadata
    cache_enabled: bool = Field(default=True)
    generation_hash: Optional[str] = None


# -----------------------------
# Instagram copy output models
# -----------------------------

class IGCaption(BaseModel):
    """A single Instagram caption with optional hashtags."""
    caption: str
    hashtags: List[str] = Field(default_factory=list)


class IGCopyPackage(BaseModel):
    """Package containing generated Instagram captions."""
    job_id: str
    brand: str
    captions: List[IGCaption] = Field(default_factory=list)


# -----------------------------
# Pipeline outputs
# -----------------------------

class RunManifest(BaseModel):
    """Execution manifest for a job run."""
    schema_version: str = Field(default="1.0.0")
    run_id: str
    job_ref: str
    job_type: str
    started_at: str
    finished_at: Optional[str] = None
    status: str  # running, succeeded, failed
    
    # Content hashes for determinism
    brief_hash: Optional[str] = None
    context_spec_hash: Optional[str] = None
    context_content_hash: Optional[str] = None
    generation_hash: Optional[str] = None
    
    # Langfuse tracing
    langfuse_trace_id: Optional[str] = None
    
    # Outputs and metadata
    artifacts: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

