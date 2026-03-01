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

    # Generation modes (Stage 5): control output strategy
    # single: generate 1 output (default)
    # variants: generate N deterministic variations
    # format: control output format flexibility
    generation_mode: Literal["single", "variants", "format"] = Field(default="single")
    caption_variants: int = Field(default=1, ge=1, le=20)  # For variants mode
    output_formats: List[Literal["md", "json", "yaml"]] = Field(default_factory=lambda: ["md"])  # For format mode

    # Context retrieval (Stage 6): query-aware corpus selection
    # glob: load files matching globs (default/legacy)
    # retrieve: deterministic keyword retrieval based on query
    context_mode: Literal["glob", "retrieve"] = Field(default="glob")
    context_query: Optional[str] = None  # Query string for retrieve mode
    retrieval_top_k: int = Field(default=10, ge=1, le=100)  # Max items to retrieve
    retrieval_method: Literal["keyword"] = Field(default="keyword")  # Only keyword for Stage 6A

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
    
    Stage 6: Supports both glob-based and retrieval-based context loading.
    """
    schema_version: str = Field(default="1.0.0")
    job_ref: Optional[str] = None
    job_type: Optional[str] = None
    brand: Optional[str] = None
    
    # Selectors for including files (glob mode)
    selectors: List[ContextSelector] = Field(default_factory=list)
    
    # Stage 6: Retrieval mode configuration
    strategy: Literal["glob", "retrieve"] = Field(default="glob")
    query: Optional[str] = None  # Query string for retrieve strategy
    retrieval_config: Optional[Dict[str, Any]] = None  # All parameters affecting retrieval
    selected_items: List[Dict[str, Any]] = Field(default_factory=list)  # Ordered list of selected items
    
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

class InputSnapshot(BaseModel):
    """Metadata for a canonical input snapshot."""
    path: str  # Relative to run directory, e.g., "inputs/brief.resolved.json"
    sha256: str
    bytes: int
    
    
class DoctrineReference(BaseModel):
    """Reference to doctrine version used in execution.
    
    Phase 1.0 Determinism: resolved_at is excluded from serialization to ensure
    deterministic manifests. Only content-based fields (doctrine_id, version, sha256)
    participate in authoritative artifacts.
    """
    doctrine_id: str  # e.g., "prompts/instagram_copy"
    version: str  # e.g., "v1.0.0"
    sha256: str  # Hash of doctrine content
    resolved_at: str | None = Field(default=None, exclude=True)  # Excluded for determinism
    resolved_path: str | None = None  # Path where doctrine was found (debug info)


class RunManifest(BaseModel):
    """Execution manifest for a job run.
    
    Phase 1.0 Determinism Guardrails:
    - All inputs are snapshotted as JSON before processing
    - run_id is derived deterministically from inputs_hash
    - job_id comes from governance (brief.job_id)
    - queue_job_id is the RQ job UUID
    - Filesystem is authoritative; DB is index-only
    """
    schema_version: str = Field(default="1.1.0")  # Bumped for Phase 1.0
    
    # Governance identifiers
    job_id: str  # From brief.job_id (governance identifier)
    run_id: str  # Deterministic: derived from inputs_hash
    queue_job_id: Optional[str] = None  # RQ job UUID (ephemeral queue identifier)
    
    # Job metadata
    job_ref: str  # Path to brief.yaml
    job_type: str
    started_at: str
    finished_at: Optional[str] = None
    status: str  # running, succeeded, failed
    
    # Phase 1.0: Canonical input snapshots
    inputs_hash: Optional[str] = None  # Hash of all input snapshots combined
    input_snapshots: Dict[str, InputSnapshot] = Field(default_factory=dict)
    # Keys: "brief", "context", "model_config", "doctrine" (if applicable)
    
    # Doctrine reference (if job type uses doctrine)
    doctrine: Optional[DoctrineReference] = None
    
    # Legacy content hashes (kept for backward compatibility)
    brief_hash: Optional[str] = None
    context_spec_hash: Optional[str] = None
    context_content_hash: Optional[str] = None
    generation_hash: Optional[str] = None
    
    # Langfuse tracing
    langfuse_trace_id: Optional[str] = None
    
    # Stage 5: Generation mode metadata (for variants, format, etc.)
    generation_metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Outputs and metadata
    artifacts: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

