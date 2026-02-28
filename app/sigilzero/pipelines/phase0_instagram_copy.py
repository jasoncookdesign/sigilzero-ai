from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from sigilzero.core.doctrine import get_doctrine_loader
from sigilzero.core.fs import ensure_dir, write_text, write_json
from sigilzero.core.hashing import sha256_bytes, sha256_json, compute_inputs_hash, derive_run_id
from sigilzero.core.langfuse_client import get_langfuse
from sigilzero.core.model import generate_text
from sigilzero.core.prompting import load_prompt_template
from sigilzero.core.schemas import (
    BriefSpec,
    ContextSpec,
    ContextSelector,
    DoctrineReference,
    GenerationSpec,
    IGCopyPackage,
    IGCaption,
    InputSnapshot,
    RunManifest,
)


_LEGACY_ALIAS_WARNING_EMITTED = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_repo_path(repo_root: str, rel_path: str) -> Path:
    if Path(rel_path).is_absolute():
        raise ValueError("job_ref must be relative")

    parts = Path(rel_path).parts
    if not parts or parts[0] != "jobs" or any(part == ".." for part in parts):
        raise ValueError("job_ref must resolve under jobs/")

    repo_root_path = Path(repo_root).resolve()
    p = (repo_root_path / rel_path).resolve()

    try:
        p.relative_to(repo_root_path)
    except ValueError:
        raise ValueError("job_ref resolves outside repository root")

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
    """Phase 1.0: Deterministic governance pipeline with canonical input snapshots.
    
    Determinism Guardrails:
    1. All inputs written as JSON snapshots BEFORE processing
    2. run_id derived deterministically from inputs_hash
    3. job_id comes from brief (governance identifier)
    4. Doctrine loaded and hashed
    5. Filesystem authoritative; manifest is source of truth
    """
    params = params or {}
    started_monotonic = time.monotonic()

    # Phase 1: Resolve and validate brief
    brief_path = _resolve_repo_path(repo_root, job_ref)
    brief_data = _read_yaml(brief_path)
    brief = BriefSpec.model_validate(brief_data)
    
    # Get queue job ID from params (RQ job UUID)
    queue_job_id = params.get("queue_job_id")
    
    # Phase 1.0: Create temp directory for atomic run creation
    # Canonical layout: artifacts/<job_id>/<run_id>/...
    # Use per-job .tmp/ subdirectory to avoid polluting run listings.
    job_root = Path(repo_root) / "artifacts" / brief.job_id
    tmp_base = job_root / ".tmp"
    ensure_dir(tmp_base)
    temp_id = f"tmp-{uuid.uuid4().hex[:16]}"
    temp_dir = tmp_base / temp_id
    ensure_dir(temp_dir / "inputs")
    ensure_dir(temp_dir / "outputs")
    
    # Phase 1.0 INVARIANT: Write canonical JSON snapshots FIRST
    # These snapshots are the source of truth for inputs_hash computation
    
    # 1. Brief snapshot
    brief_resolved = brief.model_dump(exclude={"brief_hash", "repo_commit"})
    write_json(temp_dir / "inputs" / "brief.resolved.json", brief_resolved)
    brief_snapshot_bytes = (temp_dir / "inputs" / "brief.resolved.json").read_bytes()
    brief_snapshot_hash = sha256_bytes(brief_snapshot_bytes)
    
    # 2. Context spec and content
    context_spec = ContextSpec(
        job_ref=job_ref,
        job_type=brief.job_type,
        brand=brief.brand,
        selectors=[
            ContextSelector(root="corpus", include_globs=["identity/*.md", "strategy/*.md", "artifacts/*.md"]),
        ],
    )
    context_content, context_content_hash = _materialize_context(repo_root, context_spec)
    
    # Write context snapshot
    context_resolved = {
        "spec": context_spec.model_dump(exclude={"context_spec_hash"}),
        "content": context_content,
        "content_hash": context_content_hash,
    }
    write_json(temp_dir / "inputs" / "context.resolved.json", context_resolved)
    context_snapshot_bytes = (temp_dir / "inputs" / "context.resolved.json").read_bytes()
    context_snapshot_hash = sha256_bytes(context_snapshot_bytes)
    
    # 3. Model configuration
    model_config = {
        "provider": os.getenv("LLM_PROVIDER", "openai"),
        "model": os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),
        "top_p": float(os.getenv("LLM_TOP_P", "1.0")),
        "response_schema": "response_schemas/ig_copy_package",
        "response_schema_version": "v1.0.0",
        "cache_enabled": True,
    }
    write_json(temp_dir / "inputs" / "model_config.json", model_config)
    model_snapshot_bytes = (temp_dir / "inputs" / "model_config.json").read_bytes()
    model_snapshot_hash = sha256_bytes(model_snapshot_bytes)
    
    # 4. Doctrine (prompt template) - Phase 1.0 governance requirement
    doctrine_loader = get_doctrine_loader(repo_root)
    template_id = "prompts/instagram_copy"
    template_version = "v1.0.0"
    prompt_template, doctrine_ref = doctrine_loader.load_doctrine(
        doctrine_id=template_id,
        version=template_version,
        filename="template.md"
    )
    
    # Write doctrine snapshot
    doctrine_resolved = {
        "doctrine_id": doctrine_ref.doctrine_id,
        "version": doctrine_ref.version,
        "content": prompt_template,
        "sha256": doctrine_ref.sha256,
    }
    write_json(temp_dir / "inputs" / "doctrine.resolved.json", doctrine_resolved)
    doctrine_snapshot_bytes = (temp_dir / "inputs" / "doctrine.resolved.json").read_bytes()
    doctrine_snapshot_hash = sha256_bytes(doctrine_snapshot_bytes)
    
    # Phase 1.0 INVARIANT: Compute inputs_hash from snapshot hashes
    snapshot_hashes = {
        "brief": brief_snapshot_hash,
        "context": context_snapshot_hash,
        "model_config": model_snapshot_hash,
        "doctrine": doctrine_snapshot_hash,
    }
    inputs_hash = compute_inputs_hash(snapshot_hashes)
    
    # Phase 1.0 INVARIANT: Derive deterministic run_id from inputs_hash
    base_run_id = derive_run_id(inputs_hash)
    
    # Phase 1.0 COLLISION SEMANTICS: Idempotent replay with deterministic suffix
    #
    # Rules:
    # 1. If artifacts/runs/<base_run_id> does NOT exist: use it.
    # 2. If it exists:
    #    a) Read its manifest.json and compare manifest.inputs_hash to computed inputs_hash
    #    b) If SAME: treat as idempotent replay; return existing run_id (no new run directory)
    #    c) If DIFFERENT: scan for deterministic suffix -2, -3, ... 
    #       - For each suffixed dir, check if manifest.inputs_hash matches
    #       - If match found: return that run_id (idempotent replay)
    #       - Otherwise: use next available integer suffix
    #
    # This ensures:
    # - Same inputs => same run_id (idempotent)
    # - Different inputs => different run_id (deterministic collision resolution)
    # - No orphaned staging dirs (temp_dir cleaned up in finally)
    
    runs_root = job_root
    legacy_runs_root = Path(repo_root) / "artifacts" / "runs"
    ensure_dir(runs_root)
    ensure_dir(legacy_runs_root)
    run_id = None
    final_run_dir = None
    symlink_actions: List[str] = []
    promoted_legacy = False
    
    def _read_manifest_inputs_hash(dir_path: Path) -> str | None:
        """Read inputs_hash from manifest.json, return None if not found/invalid."""
        manifest_path = dir_path / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            with manifest_path.open("r") as f:
                data = json.load(f)
                return data.get("inputs_hash")
        except Exception:
            return None
    
    def _candidate_dirs(candidate_run_id: str) -> List[Path]:
        dirs: List[Path] = []
        canonical = runs_root / candidate_run_id
        legacy = legacy_runs_root / candidate_run_id
        if canonical.exists():
            dirs.append(canonical)
        if legacy.exists() and legacy not in dirs:
            dirs.append(legacy)
        return dirs

    def _ensure_legacy_symlink(candidate_run_id: str) -> None:
        nonlocal symlink_actions
        global _LEGACY_ALIAS_WARNING_EMITTED
        legacy_path = legacy_runs_root / candidate_run_id
        if legacy_path.exists():
            return
        try:
            target_rel = Path("..") / brief.job_id / candidate_run_id
            legacy_path.symlink_to(target_rel)
            symlink_actions.append(f"legacy_alias_created:{legacy_path}->{target_rel}")
        except OSError:
            if not _LEGACY_ALIAS_WARNING_EMITTED:
                print("[legacy_alias] unable to create artifacts/runs symlink; continuing with canonical path only")
                _LEGACY_ALIAS_WARNING_EMITTED = True
            symlink_actions.append("legacy_alias_failed")

    def _promote_legacy_to_canonical(candidate_run_id: str, existing_path: Path) -> Path:
        nonlocal promoted_legacy
        canonical_path = runs_root / candidate_run_id
        legacy_path = legacy_runs_root / candidate_run_id

        # Already canonical
        if existing_path == canonical_path:
            return canonical_path

        # If canonical exists, keep using canonical
        if canonical_path.exists():
            return canonical_path

        # Promote legacy directory to canonical layout
        if legacy_path.exists() and not legacy_path.is_symlink():
            legacy_path.rename(canonical_path)
            promoted_legacy = True
            _ensure_legacy_symlink(candidate_run_id)
            return canonical_path

        # If legacy is symlink, rely on canonical target if available
        if legacy_path.is_symlink() and canonical_path.exists():
            return canonical_path

        return existing_path

    # Check base run_id across canonical + legacy locations
    base_candidates = _candidate_dirs(base_run_id)
    if not base_candidates:
        # No collision, use canonical base run_id
        run_id = base_run_id
        final_run_dir = runs_root / base_run_id
    else:
        # Collision: check if idempotent replay in any known location
        for candidate in base_candidates:
            existing_hash = _read_manifest_inputs_hash(candidate)
            if existing_hash == inputs_hash:
                run_id = base_run_id
                final_run_dir = _promote_legacy_to_canonical(base_run_id, candidate)
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                print(
                    f"[run_header] job_id={brief.job_id} job_ref={job_ref} inputs_hash={inputs_hash} "
                    f"run_id={run_id} queue_job_id={queue_job_id} doctrine={doctrine_ref.version}/{doctrine_ref.sha256}"
                )
                elapsed = time.monotonic() - started_monotonic
                print(
                    f"[run_footer] status=idempotent_replay artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
                    f"actions={','.join(symlink_actions) or 'none'}"
                )
                return {"run_id": run_id, "artifact_dir": str(final_run_dir), "idempotent_replay": True}

        # Different inputs_hash: scan deterministic suffixes across canonical + legacy
        suffix = 2
        while True:
            suffixed_run_id = f"{base_run_id}-{suffix}"
            suffixed_candidates = _candidate_dirs(suffixed_run_id)
            if not suffixed_candidates:
                # Found next available deterministic suffix in canonical location
                run_id = suffixed_run_id
                final_run_dir = runs_root / suffixed_run_id
                break

            # Check if any suffixed run is idempotent replay
            for candidate in suffixed_candidates:
                suffixed_hash = _read_manifest_inputs_hash(candidate)
                if suffixed_hash == inputs_hash:
                    run_id = suffixed_run_id
                    final_run_dir = _promote_legacy_to_canonical(suffixed_run_id, candidate)
                    if temp_dir.exists():
                        shutil.rmtree(temp_dir)
                    print(
                        f"[run_header] job_id={brief.job_id} job_ref={job_ref} inputs_hash={inputs_hash} "
                        f"run_id={run_id} queue_job_id={queue_job_id} doctrine={doctrine_ref.version}/{doctrine_ref.sha256}"
                    )
                    elapsed = time.monotonic() - started_monotonic
                    print(
                        f"[run_footer] status=idempotent_replay artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
                        f"actions={','.join(symlink_actions) or 'none'}"
                    )
                    return {"run_id": run_id, "artifact_dir": str(final_run_dir), "idempotent_replay": True}

            suffix += 1
            if suffix > 1000:
                raise RuntimeError(f"Exceeded maximum collision suffix for run_id {base_run_id}")
    
    if run_id is None or final_run_dir is None:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise RuntimeError("Failed to resolve deterministic run destination")

    print(
        f"[run_header] job_id={brief.job_id} job_ref={job_ref} inputs_hash={inputs_hash} "
        f"run_id={run_id} queue_job_id={queue_job_id} doctrine={doctrine_ref.version}/{doctrine_ref.sha256}"
    )
    
    # Create input snapshot metadata for manifest
    input_snapshots = {
        "brief": InputSnapshot(
            path="inputs/brief.resolved.json",
            sha256=brief_snapshot_hash,
            bytes=len(brief_snapshot_bytes),
        ),
        "context": InputSnapshot(
            path="inputs/context.resolved.json",
            sha256=context_snapshot_hash,
            bytes=len(context_snapshot_bytes),
        ),
        "model_config": InputSnapshot(
            path="inputs/model_config.json",
            sha256=model_snapshot_hash,
            bytes=len(model_snapshot_bytes),
        ),
        "doctrine": InputSnapshot(
            path="inputs/doctrine.resolved.json",
            sha256=doctrine_snapshot_hash,
            bytes=len(doctrine_snapshot_bytes),
        ),
    }
    
    # Langfuse trace
    lf = get_langfuse()
    trace_id = None
    if lf is not None:
        trace = lf.trace(
            name=f"job:{brief.job_type}",
            input={"job_id": brief.job_id, "run_id": run_id, "inputs_hash": inputs_hash},
            metadata={"job_id": brief.job_id, "brand": brief.brand, "queue_job_id": queue_job_id},
        )
        trace_id = trace.id
    
    # Phase 1.0: Create manifest with governance fields
    manifest = RunManifest(
        schema_version="1.1.0",  # Phase 1.0
        job_id=brief.job_id,  # Governance identifier from brief
        run_id=run_id,  # Deterministic from inputs
        queue_job_id=queue_job_id,  # RQ job UUID (ephemeral)
        job_ref=job_ref,
        job_type=brief.job_type,
        started_at=_utc_now(),
        status="running",
        inputs_hash=inputs_hash,
        input_snapshots={k: v.model_dump() for k, v in input_snapshots.items()},
        doctrine=doctrine_ref.model_dump(),
        # Legacy hashes (backward compatibility)
        brief_hash=sha256_json(brief.model_dump(exclude={"brief_hash", "repo_commit"})),
        context_spec_hash=sha256_json(context_spec.model_dump(exclude={"context_spec_hash"})),
        context_content_hash=context_content_hash,
        langfuse_trace_id=trace_id,
    )

    failed_exc: Exception | None = None

    try:
        # Generation spec (using model_config from snapshot)
        gen_spec = GenerationSpec(
            provider=model_config["provider"],
            model=model_config["model"],
            temperature=model_config["temperature"],
            top_p=model_config["top_p"],
            prompt_template=template_id,
            prompt_template_version=template_version,
            context_content_hash=context_content_hash,
            response_schema=model_config["response_schema"],
            response_schema_version=model_config["response_schema_version"],
            cache_enabled=model_config["cache_enabled"],
        )
        gen_spec.generation_hash = sha256_json(gen_spec.model_dump(exclude={"generation_hash"}))
        manifest.generation_hash = gen_spec.generation_hash

        # Format template with brief and context
        prompt = prompt_template.format(
            brief=f"Brand: {brief.brand}\nArtist: {brief.artist or 'N/A'}\nTitle: {brief.title or 'N/A'}\nTone: {', '.join(brief.tone_tags)}\n\nIG Settings:\nCaptions needed: {brief.ig.caption_count}\nHashtags needed: {brief.ig.hashtag_count}\nMax chars: {brief.ig.max_caption_chars}\nInclude CTA: {brief.ig.include_cta}\nInclude Emojis: {brief.ig.include_emojis}",
            context_items=context_content,
        )

        if lf is not None:
            span_gen = lf.span(trace_id=trace_id, name="generate_instagram_copy", input={"generation_hash": gen_spec.generation_hash})
        else:
            span_gen = None

        # Helper: parse raw text into captions
        def _parse_captions(raw: str) -> List[IGCaption]:
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
            return captions

        # Stage 5: Support generation modes
        variants: List[Dict[str, Any]] = []
        seeds_used = {}
        
        # Determine variant count based on mode
        if brief.generation_mode in ("single", "format"):
            num_variants = 1
        else:  # variants mode
            num_variants = brief.caption_variants
        
        for variant_idx in range(num_variants):
            # Compute deterministic seed for this variant
            if brief.generation_mode == "variants":
                seed_input = f"{inputs_hash}:variant:{variant_idx}"
                seed_hex = sha256_bytes(seed_input.encode("utf-8"))
                # Extract just the hex part (strip "sha256:" prefix)
                hex_only = seed_hex.replace("sha256:", "")
                # Take first 8 chars of hex as integer seed
                seed = int(hex_only[:8], 16)
                seeds_used[variant_idx] = seed_hex
            else:
                seed = None
                
            # Generate with optional seed
            gen_spec_dict = gen_spec.model_dump()
            if seed is not None:
                gen_spec_dict["seed"] = seed
                
            raw = generate_text(prompt=prompt, generation_spec=gen_spec_dict)
            captions = _parse_captions(raw)
            
            # Enforce count (truncate/pad)
            captions = captions[: brief.ig.caption_count]
            while len(captions) < brief.ig.caption_count:
                captions.append(IGCaption(caption="", hashtags=[]))
            
            pkg = IGCopyPackage(
                job_id=brief.job_id,
                brand=brief.brand,
                captions=captions,
            )
            variants.append({
                "variant_index": variant_idx,
                "seed": seed_hex if seed is not None else None,
                "captions": [c.model_dump() for c in pkg.captions],
            })

        if span_gen is not None:
            span_gen.end(output={"variants_count": len(variants)})

        # Record seed metadata in manifest if variants mode
        if brief.generation_mode == "variants":
            manifest.generation_metadata = {
                "generation_mode": brief.generation_mode,
                "variant_count": num_variants,
                "seed_strategy": "sha256(inputs_hash + ':variant:' + idx)",
                "seeds": seeds_used,
            }
        else:
            manifest.generation_metadata = {
                "generation_mode": brief.generation_mode,
                "variant_count": num_variants,
            }

        # Write outputs based on generation mode
        # Primary variant is always index 0
        primary_variant = variants[0]
        
        # Mode A (single) & Mode B (variants): write markdown with primary variant for backward compatibility
        md_lines: List[str] = [f"# Instagram Captions ({brief.brand})", f"- job_id: {brief.job_id}", f"- run_id: {run_id}", ""]
        
        if brief.generation_mode == "variants":
            md_lines.append(f"- generation_mode: variants")
            md_lines.append(f"- total_variants: {num_variants}")
            md_lines.append("")
        
        for i, cap_dict in enumerate(primary_variant["captions"], 1):
            md_lines.append(f"## Caption {i}")
            md_lines.append(cap_dict["caption"].strip())
            md_lines.append("")
        
        out_md = "\n".join(md_lines).strip() + "\n"
        out_path = temp_dir / "outputs" / "instagram_captions.md"
        write_text(out_path, out_md)
        
        # Record artifact hashes
        out_hash = sha256_bytes(out_md.encode("utf-8"))
        manifest.artifacts["outputs/instagram_captions.md"] = {"sha256": out_hash, "bytes": len(out_md.encode('utf-8'))}
        
        # Mode B (variants): write individual variant files
        if brief.generation_mode == "variants" and num_variants > 1:
            variants_dir = temp_dir / "outputs" / "variants"
            ensure_dir(variants_dir)
            
            for variant_data in variants:
                var_idx = variant_data["variant_index"]
                var_lines: List[str] = [f"# Variant {var_idx + 1}", ""]
                for i, cap_dict in enumerate(variant_data["captions"], 1):
                    var_lines.append(f"## Caption {i}")
                    var_lines.append(cap_dict["caption"].strip())
                    var_lines.append("")
                var_md = "\n".join(var_lines).strip() + "\n"
                
                var_path = variants_dir / f"{var_idx + 1:02d}.md"
                write_text(var_path, var_md)
                var_hash = sha256_bytes(var_md.encode("utf-8"))
                manifest.artifacts[f"outputs/variants/{var_idx + 1:02d}.md"] = {"sha256": var_hash, "bytes": len(var_md.encode('utf-8'))}
            
            # Write variants.json with full data
            variants_json = json.dumps(variants, indent=2, ensure_ascii=False)
            variants_json_path = variants_dir / "variants.json"
            write_text(variants_json_path, variants_json)
            var_json_hash = sha256_bytes(variants_json.encode("utf-8"))
            manifest.artifacts["outputs/variants/variants.json"] = {"sha256": var_json_hash, "bytes": len(variants_json.encode('utf-8'))}
        
        # Mode C (format): write additional output formats
        if brief.generation_mode == "format":
            primary_captions = [c["caption"] for c in primary_variant["captions"]]
            
            if "json" in brief.output_formats:
                json_data = {
                    "job_id": brief.job_id,
                    "brand": brief.brand,
                    "captions": primary_captions,
                }
                json_text = json.dumps(json_data, indent=2, ensure_ascii=False)
                json_path = temp_dir / "outputs" / "instagram_captions.json"
                write_text(json_path, json_text)
                json_hash = sha256_bytes(json_text.encode("utf-8"))
                manifest.artifacts["outputs/instagram_captions.json"] = {"sha256": json_hash, "bytes": len(json_text.encode('utf-8'))}
            
            if "yaml" in brief.output_formats:
                yaml_data = {
                    "job_id": brief.job_id,
                    "brand": brief.brand,
                    "captions": primary_captions,
                }
                yaml_text = yaml.safe_dump(yaml_data, default_flow_style=False, sort_keys=False)
                yaml_path = temp_dir / "outputs" / "instagram_captions.yaml"
                write_text(yaml_path, yaml_text)
                yaml_hash = sha256_bytes(yaml_text.encode("utf-8"))
                manifest.artifacts["outputs/instagram_captions.yaml"] = {"sha256": yaml_hash, "bytes": len(yaml_text.encode('utf-8'))}

        manifest.status = "succeeded"
        manifest.finished_at = _utc_now()

    except Exception as e:
        manifest.status = "failed"
        manifest.finished_at = _utc_now()
        manifest.error = f"{type(e).__name__}: {e}"
        failed_exc = e
    finally:
        # Always write manifest
        write_json(temp_dir / "manifest.json", json.loads(manifest.model_dump_json()))

    # Atomically rename completed temp run to canonical destination
    try:
        temp_dir.rename(final_run_dir)
    except Exception as rename_error:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise RuntimeError(f"Failed to atomically finalize run directory {final_run_dir}: {rename_error}") from rename_error

    _ensure_legacy_symlink(run_id)

    elapsed = time.monotonic() - started_monotonic
    actions = []
    if promoted_legacy:
        actions.append("promoted_legacy")
    actions.extend(symlink_actions)
    print(
        f"[run_footer] status={manifest.status} artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
        f"actions={','.join(actions) or 'none'}"
    )

    if failed_exc is not None:
        raise RuntimeError(manifest.error or "Pipeline failed") from failed_exc

    return {"run_id": run_id, "artifact_dir": str(final_run_dir)}
