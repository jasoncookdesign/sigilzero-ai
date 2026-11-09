# Documentation index

A routing map from each document to the part of the project it is the source of
truth for. Before completing a change, find the row(s) whose subject your change
touched and update those documents **in the same change** — stale docs are defects.
When you add or remove a document, or add a subsystem, update this index too.

## Top level

| Document | Source of truth for |
|---|---|
| [README.md](README.md) | Project overview, architecture summary, CLI/smoke commands, development setup, adding pipelines, release checklist |

## docs/

| Document | Source of truth for |
|---|---|
| [docs/05_generation_modes.md](docs/05_generation_modes.md) | Generation modes subsystem: single/variants/format mode contract, seed derivation, output layout per mode, determinism validation |
| [docs/07_brand_compliance_scoring.md](docs/07_brand_compliance_scoring.md) | Brand compliance scoring pipeline: `phase0_brand_compliance_score.py` interface, snapshot layout, response schema, DoD |
| [docs/08_chainable_pipelines.md](docs/08_chainable_pipelines.md) | Chainable pipeline contract: `prior_artifact.resolved.json` snapshot, chain metadata, determinism guarantees for composed stages |
| [docs/10_schema_versioning_migrations.md](docs/10_schema_versioning_migrations.md) | Schema migration architecture: `migrations.py` framework, `migrate_schemas.py` CLI, version lineage (1.0.0 → 1.2.0), operational procedures |
| [docs/11_observability_langfuse.md](docs/11_observability_langfuse.md) | Langfuse observability integration: `langfuse_client.py` + `observability.py` API, tracing boundary, graceful-degradation contract |
| [docs/12_release_candidate_hardening.md](docs/12_release_candidate_hardening.md) | Stage 12 hardening changes: registry completeness, `smoke_release_candidate_hardening.py` checks, canonical manifest write guarantees |
| [docs/ARCHITECTURE_PHASE_1.0_DETERMINISM.md](docs/ARCHITECTURE_PHASE_1.0_DETERMINISM.md) | Authoritative specification of all 7 determinism invariants: snapshot format, hash algorithm, `run_id` derivation, verification procedures |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Operator guide: job creation patterns, use-case recipes, pipeline composition strategies, how to add new job types |
| [docs/VISUAL_ARCHITECTURE_PHASE_1.0.md](docs/VISUAL_ARCHITECTURE_PHASE_1.0.md) | ASCII diagram reference for the determinism chain (input → snapshot → hash → `inputs_hash` → `run_id`), chaining model, no-silent-drift invariant |
