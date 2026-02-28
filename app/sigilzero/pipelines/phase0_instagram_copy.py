from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from sigilzero.core.fs import ensure_dir, write_text, write_json
from sigilzero.core.hashing import sha256_bytes, sha256_json
from sigilzero.core.langfuse_client import get_langfuse
from sigilzero.core.model import generate_text
from sigilzero.core.prompting import load_prompt_template
from sigilzero.core.schemas import (
    BriefSpec,
    ContextSpec,
    ContextSelector,
    GenerationSpec,
    IGCopyPackage,
    IGCaption,
    RunManifest,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_repo_path(repo_root: str, rel_path: str) -> Path:
    p = Path(repo_root) / rel_path
    if not p.exists():
        raise FileNotFoundError(f"job_ref not found at {p}")
    return p


def _materialize_context(repo_root: str, spec: ContextSpec) -> Tuple[str, str]:
    """Return (context_content, context_content_hash)."""
    chunks: List[str] = []

    for sel in spec.selectors:
        root = Path(repo_root) / sel.root
        if not root.exists():
            continue

        # gather files
        matched: List[Path] = []
        for pat in sel.include_globs:
            matched.extend(sorted(root.glob(pat)))

        # apply excludes
        excluded: set[Path] = set()
        for pat in sel.exclude_globs:
            excluded.update(set(root.glob(pat)))

        files = [p for p in matched if p.is_file() and p not in excluded][: sel.max_files]

        for fp in files:
            rel = fp.relative_to(Path(repo_root))
            txt = fp.read_text(encoding="utf-8", errors="replace")
            chunks.append(f"\n\n# FILE: {rel.as_posix()}\n{txt}")

    content = "".join(chunks).strip()
    content_hash = sha256_bytes(content.encode("utf-8"))
    return content, content_hash


def execute_instagram_copy_pipeline(repo_root: str, job_ref: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Phase 0: brief.yaml -> instagram_captions.md + manifest.json (local-first)."""
    params = params or {}

    # Resolve + validate brief
    brief_path = _resolve_repo_path(repo_root, job_ref)
    brief_raw = brief_path.read_bytes()
    brief_file_hash = sha256_bytes(brief_raw)

    brief_data = _read_yaml(brief_path)
    brief = BriefSpec.model_validate(brief_data)
    brief.brief_hash = sha256_json(brief.model_dump(exclude={"brief_hash", "repo_commit"}))

    # Create run folder
    run_id = str(uuid.uuid4())
    run_dir = Path(repo_root) / "artifacts" / "runs" / run_id
    ensure_dir(run_dir / "inputs")
    ensure_dir(run_dir / "outputs")

    # Save input snapshot
    (run_dir / "inputs" / "brief.yaml").write_bytes(brief_raw)

    # Langfuse trace
    lf = get_langfuse()
    trace_id = None
    if lf is not None:
        trace = lf.trace(
            name=f"job:{brief.job_type}",
            input={"job_ref": job_ref, "brief_hash": brief.brief_hash, "brief_file_hash": brief_file_hash},
            metadata={"job_id": brief.job_id, "brand": brief.brand},
        )
        trace_id = trace.id

    manifest = RunManifest(
        run_id=run_id,
        job_ref=job_ref,
        job_type=brief.job_type,
        started_at=_utc_now(),
        status="running",
        brief_hash=brief.brief_hash,
        langfuse_trace_id=trace_id,
    )

    try:
        # Build context spec (job-centric; avoid release fields)
        context_spec = ContextSpec(
            job_ref=job_ref,
            job_type=brief.job_type,
            brand=brief.brand,
            selectors=[
                ContextSelector(root="corpus", include_globs=["identity/*.md", "strategy/*.md", "artifacts/*.md"]),
            ],
        )
        context_spec.context_spec_hash = sha256_json(context_spec.model_dump(exclude={"context_spec_hash"}))
        manifest.context_spec_hash = context_spec.context_spec_hash

        # Materialize context pack (content + hash)
        if lf is not None:
            span_ctx = lf.span(trace_id=trace_id, name="materialize_context_pack", input=context_spec.model_dump())
        else:
            span_ctx = None

        context_content, context_content_hash = _materialize_context(repo_root, context_spec)
        manifest.context_content_hash = context_content_hash

        if span_ctx is not None:
            span_ctx.end(output={"context_content_hash": context_content_hash, "chars": len(context_content)})

        # Prompt + generation spec
        template_id = "prompts/instagram_copy"
        template_version = "v1.0.0"
        prompt_template = load_prompt_template(repo_root, template_id, template_version)

        gen_spec = GenerationSpec(
            provider=os.getenv("LLM_PROVIDER", "openai"),
            model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            top_p=float(os.getenv("LLM_TOP_P", "1.0")),
            prompt_template=template_id,
            prompt_template_version=template_version,
            context_content_hash=context_content_hash,
            response_schema="response_schemas/ig_copy_package",
            response_schema_version="v1.0.0",
            cache_enabled=True,
        )
        gen_spec.generation_hash = sha256_json(gen_spec.model_dump(exclude={"generation_hash"}))
        manifest.generation_hash = gen_spec.generation_hash

        # Model call (single-shot)
        # Format template with brief and context
        prompt = prompt_template.format(
            brief=f"Brand: {brief.brand}\nArtist: {brief.artist or 'N/A'}\nTitle: {brief.title or 'N/A'}\nTone: {', '.join(brief.tone_tags)}\n\nIG Settings:\nCaptions needed: {brief.ig.caption_count}\nHashtags needed: {brief.ig.hashtag_count}\nMax chars: {brief.ig.max_caption_chars}\nInclude CTA: {brief.ig.include_cta}\nInclude Emojis: {brief.ig.include_emojis}",
            context_items=context_content,
        )

        if lf is not None:
            span_gen = lf.span(trace_id=trace_id, name="generate_instagram_copy", input={"generation_hash": gen_spec.generation_hash})
        else:
            span_gen = None

        raw = generate_text(prompt=prompt, generation_spec=gen_spec.model_dump())

        if span_gen is not None:
            span_gen.end(output={"raw_chars": len(raw)})

        # Parse into package (very small, safe parser)
        captions: List[IGCaption] = []
        lines = [ln.rstrip() for ln in raw.splitlines()]
        current: List[str] = []
        for ln in lines:
            if ln.strip().startswith("---") and current:
                cap = "\n".join(current).strip()
                if cap:
                    captions.append(IGCaption(caption=cap, hashtags=[]))
                current = []
            else:
                current.append(ln)
        if current:
            cap = "\n".join(current).strip()
            if cap:
                captions.append(IGCaption(caption=cap, hashtags=[]))

        # enforce count (truncate/pad)
        captions = captions[: brief.ig.caption_count]
        while len(captions) < brief.ig.caption_count:
            captions.append(IGCaption(caption="", hashtags=[]))

        pkg = IGCopyPackage(
            job_id=brief.job_id,
            brand=brief.brand,
            captions=captions,
        )

        # Render markdown artifact
        md_lines: List[str] = [f"# Instagram Captions ({brief.brand})", f"- job_id: {brief.job_id}", f"- run_id: {run_id}", ""]
        for i, c in enumerate(pkg.captions, 1):
            md_lines.append(f"## Caption {i}")
            md_lines.append(c.caption.strip())
            md_lines.append("")
        out_md = "\n".join(md_lines).strip() + "\n"

        out_path = run_dir / "outputs" / "instagram_captions.md"
        write_text(out_path, out_md)

        # Record artifact hashes
        out_hash = sha256_bytes(out_md.encode("utf-8"))
        manifest.artifacts["outputs/instagram_captions.md"] = {"sha256": out_hash, "bytes": len(out_md.encode('utf-8'))}

        manifest.status = "succeeded"
        manifest.finished_at = _utc_now()

    except Exception as e:
        manifest.status = "failed"
        manifest.finished_at = _utc_now()
        manifest.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        # Always write manifest
        write_json(run_dir / "manifest.json", json.loads(manifest.model_dump_json()))

    return {"run_id": run_id, "artifact_dir": str(run_dir)}
