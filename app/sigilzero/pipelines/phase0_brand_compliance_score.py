"""
Brand Compliance Scoring Pipeline (Stage 7)

Evaluates content against brand identity and strategy guidelines.

Determinism Guardrails:
1. All inputs written as JSON snapshots BEFORE processing
2. run_id derived deterministically from inputs_hash
3. job_id comes from brief (governance identifier)
4. Doctrine loaded and hashed
5. Filesystem authoritative; manifest is source of truth
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from sigilzero.core.doctrine import get_doctrine_loader
from sigilzero.core.fs import ensure_dir, write_json
from sigilzero.core.hashing import sha256_bytes, sha256_json, compute_inputs_hash, derive_run_id
from sigilzero.core.langfuse_client import get_langfuse
from sigilzero.core.model import generate_text
from sigilzero.core.schemas import (
    DoctrineReference,
    GenerationSpec,
    InputSnapshot,
    RunManifest,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_yaml(path: Path) -> Dict[str, Any]:
    """Read YAML file, return dict."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_repo_path(repo_root: str, rel_path: str) -> Path:
    """Resolve job_ref safely under jobs/ directory."""
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


def run_brand_compliance_score(
    job_ref: str,
    repo_root: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Run brand compliance scoring pipeline.
    
    Args:
        job_ref: Path to brief YAML (e.g., "jobs/brand-score-001/brief.yaml")
        repo_root: Repository root path
        params: Optional parameters (queue_job_id, etc.)
    
    Returns:
        {"run_id": str, "artifact_dir": str, "idempotent_replay": bool}
    
    Enforces all 7 architectural invariants:
    1. Canonical input snapshots (brief, context, model_config, doctrine)
    2. Deterministic run_id from inputs_hash
    3. job_id from brief (governance)
    4. Doctrine versioned and hashed
    5. Filesystem authoritative persistence
    6. No silent drift
    7. Backward compatible API
    """
    params = params or {}
    started_monotonic = time.monotonic()

    # Phase 1: Resolve and validate brief
    brief_path = _resolve_repo_path(repo_root, job_ref)
    brief_data = _read_yaml(brief_path)
    
    # Minimal validation
    if not isinstance(brief_data, dict):
        raise ValueError("brief.yaml must be a dict")
    
    job_id = brief_data.get("job_id")
    job_type = brief_data.get("job_type")
    if not job_id or job_type != "brand_compliance_score":
        raise ValueError("brief must have job_id and job_type=brand_compliance_score")
    
    queue_job_id = params.get("queue_job_id")
    
    # Phase 1.0: Create temp directory for atomic run creation
    job_root = Path(repo_root) / "artifacts" / job_id
    tmp_base = job_root / ".tmp"
    ensure_dir(tmp_base)
    temp_id = f"tmp-{uuid.uuid4().hex[:16]}"
    temp_dir = tmp_base / temp_id
    ensure_dir(temp_dir / "inputs")
    ensure_dir(temp_dir / "outputs")
    
    # Phase 1.0 INVARIANT: Write canonical JSON snapshots FIRST
    # These snapshots are the source of truth for inputs_hash computation
    
    # 1. Brief snapshot (governance spec)
    brief_resolved = {
        k: v for k, v in brief_data.items()
        if k not in {"brief_hash", "repo_commit"}
    }
    write_json(temp_dir / "inputs" / "brief.resolved.json", brief_resolved)
    brief_snapshot_bytes = (temp_dir / "inputs" / "brief.resolved.json").read_bytes()
    brief_snapshot_hash = sha256_bytes(brief_snapshot_bytes)
    
    # 2. Context snapshot (content + brand identity)
    content_to_score = brief_data.get("content", {})
    brand_identity_scope = brief_data.get("brand_identity_scope", "brand_voice+positioning")
    
    # Load brand identity from corpus
    corpus_root = Path(repo_root) / "corpus"
    brand_identity_files = {}
    
    if "brand_voice" in brand_identity_scope:
        bv_path = corpus_root / "identity" / "Brand_Voice.md"
        if bv_path.exists():
            brand_identity_files["brand_voice"] = bv_path.read_text(encoding="utf-8")
    
    if "positioning" in brand_identity_scope:
        pos_path = corpus_root / "strategy" / "Positioning.md"
        if pos_path.exists():
            brand_identity_files["positioning"] = pos_path.read_text(encoding="utf-8")
    
    context_obj = {
        "job_id": job_id,
        "job_type": job_type,
        "brand_identity_scope": brand_identity_scope,
        "brand_identity_files": brand_identity_files,
        "content_to_score": content_to_score,
        "evaluation_focus": brief_data.get("evaluation_focus", ""),
    }
    write_json(temp_dir / "inputs" / "context.resolved.json", context_obj)
    context_snapshot_bytes = (temp_dir / "inputs" / "context.resolved.json").read_bytes()
    context_snapshot_hash = sha256_bytes(context_snapshot_bytes)
    
    # 3. Model config (determinism)
    model_config = {
        "provider": os.getenv("LLM_PROVIDER", "openai"),
        "model": os.getenv("LLM_MODEL", "gpt-4"),
        "temperature": 0,  # Deterministic
        "top_p": 1.0,
        "max_tokens": 2000,
        "response_format": "json",
    }
    write_json(temp_dir / "inputs" / "model_config.json", model_config)
    model_snapshot_bytes = (temp_dir / "inputs" / "model_config.json").read_bytes()
    model_snapshot_hash = sha256_bytes(model_snapshot_bytes)
    
    # 4. Doctrine (brand strategy snapshot) - Phase 1.0 governance requirement
    doctrine_loader = get_doctrine_loader(repo_root)
    doctrine_id = "brand_governance"
    doctrine_version = "v1.0.0"
    
    try:
        # Load brand strategy files as doctrine
        # Use identity/Brand_Voice.md for consistency with context loading
        strategy_files = []
        
        # Brand voice from identity (matches context loading)
        bv_path = corpus_root / "identity" / "Brand_Voice.md"
        if bv_path.exists():
            strategy_files.append(bv_path.read_text(encoding="utf-8"))
        
        # Strategy docs
        for fname in ["Marketing_Principles.md", "Positioning.md"]:
            fpath = corpus_root / "strategy" / fname
            if fpath.exists():
                strategy_files.append(fpath.read_text(encoding="utf-8"))
        
        doctrine_content = "\n\n---\n\n".join(strategy_files)
        doctrine_sha256 = sha256_bytes(doctrine_content.encode("utf-8"))
        
        # Create doctrine reference (resolved_at omitted for determinism)
        doctrine_ref = DoctrineReference(
            doctrine_id=doctrine_id,
            version=doctrine_version,
            sha256=doctrine_sha256,
            resolved_path=str(corpus_root / "strategy"),
        )
    except Exception as e:
        raise ValueError(f"Failed to load doctrine: {e}")
    
    # Write doctrine snapshot
    doctrine_resolved = {
        "doctrine_id": doctrine_ref.doctrine_id,
        "version": doctrine_ref.version,
        "sha256": doctrine_ref.sha256,
        "content": doctrine_content,
    }
    write_json(temp_dir / "inputs" / "doctrine.resolved.json", doctrine_resolved)
    doctrine_snapshot_bytes = (temp_dir / "inputs" / "doctrine.resolved.json").read_bytes()
    doctrine_snapshot_hash = sha256_bytes(doctrine_snapshot_bytes)
    
    # Phase 1.0 BLOCKER 2 FIX: Load and snapshot prompt template BEFORE inputs_hash computation
    # Template participates in inputs_hash to ensure template changes → run_id changes (no silent drift)
    try:
        template_id = "prompts/brand_compliance_score"
        template_version = "v1.0.0"
        prompt_template_raw, template_doctrine_ref = doctrine_loader.load_doctrine(
            doctrine_id=template_id,
            version=template_version,
            filename="template.md"
        )
        
        # Snapshot the template as an input
        template_resolved = {
            "doctrine_id": template_doctrine_ref.doctrine_id,
            "version": template_doctrine_ref.version,
            "sha256": template_doctrine_ref.sha256,
            "content": prompt_template_raw,
        }
        write_json(temp_dir / "inputs" / "prompt_template.resolved.json", template_resolved)
        template_snapshot_bytes = (temp_dir / "inputs" / "prompt_template.resolved.json").read_bytes()
        template_snapshot_hash = sha256_bytes(template_snapshot_bytes)
    except Exception as e:
        raise ValueError(f"Failed to load prompt template: {e}")
    
    # Phase 1.0 INVARIANT: Compute inputs_hash from snapshot hashes (including template)
    snapshot_hashes = {
        "brief": brief_snapshot_hash,
        "context": context_snapshot_hash,
        "model_config": model_snapshot_hash,
        "doctrine": doctrine_snapshot_hash,
        "prompt_template": template_snapshot_hash,  # BLOCKER 2 FIX: Template now participates in inputs_hash
    }
    inputs_hash = compute_inputs_hash(snapshot_hashes)
    
    # Phase 1.0 INVARIANT: Derive deterministic run_id from inputs_hash
    base_run_id = derive_run_id(inputs_hash)
    
    # Phase 1.0 COLLISION SEMANTICS: Idempotent replay with deterministic suffix
    runs_root = job_root
    legacy_runs_root = Path(repo_root) / "artifacts" / "runs"
    ensure_dir(runs_root)
    ensure_dir(legacy_runs_root)
    run_id = None
    final_run_dir = None
    symlink_actions: List[str] = []
    
    def _read_manifest_inputs_hash(dir_path: Path) -> Optional[str]:
        """Read inputs_hash from manifest.json."""
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
        """Get candidate run directories (canonical + legacy)."""
        dirs: List[Path] = []
        canonical = runs_root / candidate_run_id
        legacy = legacy_runs_root / candidate_run_id
        if canonical.exists():
            dirs.append(canonical)
        if legacy.exists() and legacy not in dirs:
            dirs.append(legacy)
        return dirs
    
    def _ensure_legacy_symlink(candidate_run_id: str) -> None:
        """Create legacy symlink if needed."""
        nonlocal symlink_actions
        legacy_path = legacy_runs_root / candidate_run_id
        if legacy_path.exists():
            return
        try:
            target_rel = Path("..") / job_id / candidate_run_id
            legacy_path.symlink_to(target_rel)
            symlink_actions.append(f"legacy_alias_created:{legacy_path}->{target_rel}")
        except OSError:
            pass
    
    # Check base run_id
    base_candidates = _candidate_dirs(base_run_id)
    if not base_candidates:
        run_id = base_run_id
        final_run_dir = runs_root / base_run_id
    else:
        # Collision: check idempotent replay
        for candidate in base_candidates:
            existing_hash = _read_manifest_inputs_hash(candidate)
            if existing_hash == inputs_hash:
                run_id = base_run_id
                final_run_dir = candidate
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                print(
                    f"[run_header] job_id={job_id} job_ref={job_ref} inputs_hash={inputs_hash} "
                    f"run_id={run_id} queue_job_id={queue_job_id} doctrine={doctrine_ref.version}/{doctrine_ref.sha256}"
                )
                elapsed = time.monotonic() - started_monotonic
                print(
                    f"[run_footer] status=idempotent_replay artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
                    f"actions={','.join(symlink_actions) or 'none'}"
                )
                return {"run_id": run_id, "artifact_dir": str(final_run_dir), "idempotent_replay": True}
        
        # Different inputs: scan deterministic suffixes
        suffix = 2
        while suffix <= 1000:
            suffixed_run_id = f"{base_run_id}-{suffix}"
            suffixed_candidates = _candidate_dirs(suffixed_run_id)
            if not suffixed_candidates:
                run_id = suffixed_run_id
                final_run_dir = runs_root / suffixed_run_id
                break
            
            for candidate in suffixed_candidates:
                suffixed_hash = _read_manifest_inputs_hash(candidate)
                if suffixed_hash == inputs_hash:
                    run_id = suffixed_run_id
                    final_run_dir = candidate
                    if temp_dir.exists():
                        shutil.rmtree(temp_dir)
                    print(
                        f"[run_header] job_id={job_id} job_ref={job_ref} inputs_hash={inputs_hash} "
                        f"run_id={run_id} queue_job_id={queue_job_id} doctrine={doctrine_ref.version}/{doctrine_ref.sha256}"
                    )
                    elapsed = time.monotonic() - started_monotonic
                    print(
                        f"[run_footer] status=idempotent_replay artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
                        f"actions={','.join(symlink_actions) or 'none'}"
                    )
                    return {"run_id": run_id, "artifact_dir": str(final_run_dir), "idempotent_replay": True}
            
            suffix += 1
    
    if run_id is None or final_run_dir is None:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise RuntimeError("Failed to resolve deterministic run destination")
    
    print(
        f"[run_header] job_id={job_id} job_ref={job_ref} inputs_hash={inputs_hash} "
        f"run_id={run_id} queue_job_id={queue_job_id} doctrine={doctrine_ref.version}/{doctrine_ref.sha256}"
    )
    
    # Ensure legacy symlink
    _ensure_legacy_symlink(run_id)
    
    # Create input snapshots metadata
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
        "prompt_template": InputSnapshot(  # BLOCKER 2 FIX: Template as input snapshot
            path="inputs/prompt_template.resolved.json",
            sha256=template_snapshot_hash,
            bytes=len(template_snapshot_bytes),
        ),
    }
    
    lf = get_langfuse()
    trace_id = None
    if lf is not None:
        trace = lf.trace(
            name=f"job:brand_compliance_score",
            input={"job_id": job_id, "run_id": run_id, "inputs_hash": inputs_hash},
            metadata={"job_id": job_id, "queue_job_id": queue_job_id},
        )
        trace_id = trace.id
    
    # Phase 1.0: Create manifest
    manifest = RunManifest(
        schema_version="1.1.0",
        job_id=job_id,
        run_id=run_id,
        queue_job_id=queue_job_id,
        job_ref=job_ref,
        job_type=job_type,
        started_at=_utc_now(),
        status="running",
        inputs_hash=inputs_hash,
        input_snapshots={k: v.model_dump() for k, v in input_snapshots.items()},
        doctrine=doctrine_ref.model_dump(),
        langfuse_trace_id=trace_id,
    )
    
    failed_exc: Optional[Exception] = None
    
    try:
        # Format template with context (template already loaded and snapshotted above)
        prompt = prompt_template_raw.format(
            brand_voice=context_obj.get('brand_identity_files', {}).get('brand_voice', 'N/A'),
            brand_positioning=context_obj.get('brand_identity_files', {}).get('positioning', 'N/A'),
            title=content_to_score.get('title', 'N/A'),
            body=content_to_score.get('body', 'N/A'),
            channels=', '.join(content_to_score.get('channels', [])),
        )
        
        if lf is not None and trace_id:
            span_gen = lf.span(trace_id=trace_id, name="score_brand_compliance")
        else:
            span_gen = None
        
        # Build generation spec
        gen_spec = GenerationSpec(
            provider=model_config.get("provider", "openai"),
            model=model_config.get("model", "gpt-4"),
            temperature=model_config.get("temperature", 0),
            top_p=model_config.get("top_p", 1.0),
            prompt_template=template_id,
            prompt_template_version=template_version,
            context_content_hash=context_snapshot_hash,
            response_schema="response_schemas/brand_compliance_score",
            response_schema_version="v1.0.0",
            cache_enabled=False,
        )
        gen_spec.generation_hash = sha256_json(gen_spec.model_dump(exclude={"generation_hash"}))
        
        # Call LLM
        try:
            gen_spec_dict = gen_spec.model_dump()
            response_text = generate_text(
                prompt=prompt,
                generation_spec=gen_spec_dict,
            )
        except Exception as e:
            raise RuntimeError(f"LLM call failed: {e}")
        
        # Parse response
        try:
            # Handle JSON in code fence
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = response_text.strip()
            
            compliance_output = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse LLM response as JSON: {e}\nResponse: {response_text}")
        
        if lf is not None and span_gen:
            span_gen.end(output=compliance_output)
        
        # Ensure final_run_dir exists
        ensure_dir(final_run_dir / "inputs")
        ensure_dir(final_run_dir / "outputs")
        
        # Copy inputs from temp to final (atomic finalization)
        # Copy exact snapshot filenames (model_config has no .resolved suffix)
        snapshot_files = [
            "brief.resolved.json",
            "context.resolved.json",
            "model_config.json",
            "doctrine.resolved.json",
            "prompt_template.resolved.json",  # BLOCKER 2 FIX: Include template snapshot
        ]
        for filename in snapshot_files:
            src = temp_dir / "inputs" / filename
            dst = final_run_dir / "inputs" / filename
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            else:
                raise RuntimeError(f"Expected snapshot not found: {src}")
        
        # Write outputs
        write_json(final_run_dir / "outputs" / "compliance_scores.json", compliance_output)
        
        # Finalize manifest
        manifest.status = "succeeded"
        manifest.finished_at = _utc_now()
        manifest.artifacts = {
            "compliance_scores": {
                "path": "outputs/compliance_scores.json",
                "sha256": sha256_bytes((final_run_dir / "outputs" / "compliance_scores.json").read_bytes()),
            }
        }
        
        manifest_path = final_run_dir / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(by_alias=False), f, indent=2, ensure_ascii=False)
        
        elapsed = time.monotonic() - started_monotonic
        print(
            f"[run_footer] status=succeeded artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
            f"actions={','.join(symlink_actions) or 'none'}"
        )
        
        return {"run_id": run_id, "artifact_dir": str(final_run_dir)}
    
    except Exception as e:
        failed_exc = e
        manifest.status = "failed"
        manifest.finished_at = _utc_now()
        manifest.error = str(e)
        
        manifest_path = final_run_dir / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(by_alias=False), f, indent=2, ensure_ascii=False)
        
        elapsed = time.monotonic() - started_monotonic
        print(
            f"[run_footer] status=failed artifact_dir={final_run_dir} elapsed_s={elapsed:.3f} "
            f"actions={','.join(symlink_actions) or 'none'}"
        )
        
        raise
    
    finally:
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
