This **user guide** describes how to realize the cataloged use cases with *this* deterministic, filesystem-authoritative engine—using the capabilities that already exist (and clearly labeling what requires **adding a new job type/pipeline**).

I’m going to assume the repo’s standard operating model:

* You create **job folders** under `jobs/<job_id>/` with a `brief.yaml`
* You run a job via the repo’s normal entrypoint (often `POST /jobs/run` or a CLI wrapper)
* The run produces canonical artifacts under `artifacts/<job_id>/<run_id>/`
* You verify integrity via `reindex --verify` / determinism verifiers / smoke tests

---

# 0) Mental model: how you “do anything” in this system

## The 4 building blocks you’ll use in every use case

1. **Brief (governance request)**
   `jobs/<job_id>/brief.yaml` defines:

   * `job_id` (governance ID)
   * job parameters (generation mode, formats, retrieval settings, etc.)
   * pointers to your release/artist/input data (either embedded, or referenced via corpus/docs)

2. **Context (content substrate)**
   The engine resolves context into `inputs/context.resolved.json` via either:

   * **glob mode**: select docs/files by path patterns
   * **retrieve mode** (Stage 6): deterministic keyword retrieval (BM25) using a query + top_k

3. **Doctrine (governance doctrine)**
   Doctrine is treated as an input snapshot with hash + version, recorded in manifest, and participates in `inputs_hash`. Use doctrine to lock brand voice, manifesto, positioning, models.

4. **Artifacts are the “truth”**
   All runs can be audited/reindexed/verified from filesystem alone:

   * `manifest.json`
   * `inputs/*.json`
   * `outputs/*`

## Deterministic control knobs you should rely on

* **Generation modes** (Stage 5):

  * `single` (default)
  * `variants` (deterministic per-variant seeds)
  * `format` (optional json/yaml alongside md)
* **Retrieval** (Stage 6):

  * deterministic BM25 with stable tie-breaking
  * retrieval choices are snapshotted and hashed
* **Brand compliance scoring** (Stage 7):

  * score any text against doctrine, produce structured JSON
* **Chainable pipelines** (Stage 8):

  * downstream jobs can reference **prior artifacts**; prior outputs are hashed into the new run
* **Verification**:

  * reindex + verify catches snapshot/manifest/run_id mismatches
  * determinism verifier can validate invariants for a run directory

---

# 1) Your day-to-day workflow templates

## A) Create a job

Create a folder:

```
jobs/<job_id>/
  brief.yaml
```

Where `<job_id>` is a governance identifier, e.g.:

* `release-edge-of-the-night-copy`
* `artist-nototo-bio`
* `brand-score-001`
* `optimization-001`

## B) Run a job

Use your repo’s standard invocation:

* API: `POST /jobs/run` with `job_ref: jobs/<job_id>/brief.yaml`
* or CLI if you have one

## C) Inspect outputs

Artifacts land here:

```
artifacts/<job_id>/<run_id>/
  manifest.json
  inputs/
  outputs/
```

## D) Verify

Always run:

* `reindex --verify` (or `make reindex_verify`)
* smoke tests for the stage(s) you touched

---

# 2) CORE OUTPUT LAYER

This layer is “generate doctrine-bound copy.” The system already supports **deterministic copy generation patterns** through `phase0_instagram_copy.py` (and the general pipeline architecture). For use cases beyond IG captions, you’ll typically implement them as **new job types** that reuse the same invariants and artifact doctrine structure.

## 2.1 Release-level assets (Beatport, Spotify bio, pitches, press kit summaries, etc.)

### What you can do now (no new pipeline)

Use the **instagram copy pipeline** as a generic doctrine-bound copy generator, by:

* feeding it different release context docs
* changing the “request” in the brief
* choosing `single / variants / format`

You treat `outputs/instagram_captions.md` as **the guaranteed backward-compatible “primary output.”** If you want the filename to reflect the asset type, you *still* keep `outputs/instagram_captions.md` (invariant), and optionally emit the real-named file too (as extra output).

### Recommended job pattern

* Context includes:

  * release model data (`Release_Model.md`, release YAML/JSON)
  * label doctrine (`Brand_Voice.md`, `Manifesto.md`, `Positioning.md`)
  * any existing templates you store in corpus (promo sheets, pitch formats)
* Brief asks for the specific asset type (“write Beatport description” etc.)

### Advanced: tonal variants

Use Stage 5 `variants` mode.

* Put your tone constraints in the brief (or in context docs that the doctrine references).
* The system derives deterministic per-variant seeds from inputs_hash + index.

Artifacts:

* `outputs/instagram_captions.md` (always)
* `outputs/variants/01.md`, `02.md`, …
* `outputs/variants/variants.json` (if implemented in your pipeline)

### Output formats

Use Stage 5 `format` mode with `output_formats: ["md","json","yaml"]` (when supported by the pipeline) to generate:

* a human-readable md
* structured payloads usable for Label Engine / Next.js / Obsidian ingestion

---

## 2.2 Artist identity enforcement (bios, EPK narrative, archetype classification)

### What exists today

* You can generate copy (bios, narrative framing) using the same doctrine-bound generation path.
* You can score identity copy using **brand compliance scoring** (Stage 7).

### How to do it

**Two-step recommended workflow (deterministic and auditable):**

1. **Generate bio** (copy pipeline):

* Job: `artist-<name>-bio`
* Mode:

  * `single` for one canonical bio
  * `variants` for short/long/tone options

2. **Score compliance** (brand compliance job type):

* Job: `brand-score-<name>-bio`
* Input: the generated bio (either pasted into brief/context, or pulled via chainable prior artifact)
* Output: structured scores + rewrite recommendations

### Archetype classification

If archetype classification isn’t an explicit pipeline yet:

* Implement as a new job type (see “Adding new job types” section below)
* Or encode the classifier prompt inside the existing generator job and request JSON output (`format` mode) with an `archetype` field.

---

## 2.3 Social media systems (IG captions, carousel copy, Threads, LinkedIn, TikTok hooks, campaigns)

### IG captions

This is the native path of `phase0_instagram_copy.py`.

Use:

* `single`: canonical caption
* `variants`: multiple captions
* `format`: emit structured campaign objects

### Carousel slide copy + campaign sequences

You can do this two ways:

**Option A: single job outputs a structured campaign plan**

* Use `format` mode and define a JSON schema you want:

  * slides: [{headline, body, CTA}]
  * posts: [{day, platform, copy, hashtags}]
* The pipeline emits md + json/yaml.

**Option B: chainable pipeline**

* Stage 1: generate campaign arc JSON
* Stage 2: for each day/post, generate platform-specific copy (can be deterministic by passing the arc JSON in context)
* Stage 3: brand compliance scoring for each post

If you don’t have multi-run orchestration tooling yet, Option A is the fastest.

---

# 3) GOVERNANCE & EVALUATION LAYER

This is where your system becomes “SIGIL.ZERO OS” rather than “copy generator.”

## 3.1 Brand compliance engine (Stage 7)

### Use cases covered

* Score text vs doctrine
* highlight weak phrases
* flag generic language
* detect “algorithmic sounding” copy
* propose rewrite

### How to use it

Create a `brand_compliance_score` job.

Inputs you’ll typically provide:

* The candidate text (the copy you want scored)
* The doctrine set you want enforced (voice + manifesto + positioning)

Outputs:

* `outputs/compliance_scores.json` (structured)
* plus manifest + snapshots

### Best practice: chain it

For anything you *generate*, chain compliance scoring afterwards so your governance record is traceable and replayable.

---

## 3.2 Release evaluation (mysticism index, underground index, aggression index, authenticity score)

### What exists

This is conceptually identical to compliance scoring, but with a different rubric.

If you don’t already have a “release evaluation” pipeline:

* implement as a new job type using the Stage 7 pattern
* same artifact rigor: snapshots + manifest + deterministic output schema

### How you would run it (once implemented)

* Provide release description + track notes
* Doctrine includes `Sound_Philosophy.md`, `Aesthetic_Framework.md`, any scoring rubric doc
* Output is structured JSON with your indices and recommendations

---

## 3.3 A&R support tool (demo fit, sub-series placement, rejection/acceptance emails)

Same pattern as release evaluation:

* deterministic scoring pipeline + structured schema
* optional follow-up generation pipeline to draft emails in doctrine voice

**Key governance rule for A&R decisions:**
Make the scoring output a first-class artifact. Any “decision brief” should be reconstructable from disk.

---

## 3.4 Strategic alignment checker (ecosystem map, cultural context)

Again, a scoring + commentary pipeline:

* Inputs: proposed release/event concept + references to upcoming calendar + ecosystem docs
* Output: structured recommendation and conflict warnings

Use retrieval mode heavily here:

* query doctrine/corpus for “upcoming releases”, “positioning”, “cultural risks”
* ensure selected items are snapshotted

---

# 4) STRATEGIC DESIGN SYSTEMS

These are “generate systems, not copy.” They still fit perfectly because the engine is job-based and artifact-authoritative.

## 4.1 Narrative architecture builder (release arcs, lore continuity, symbology logic)

### Recommended approach

Use `format` mode to output machine-readable structures:

* `season_arc.json`: theme map, motifs, narrative beats, planned drops
* `lore_fragments.json`: canonical fragments with IDs and tags
* `sigil_logic.json`: symbolic rules and constraints

Then:

* ingest them into your website generator / Obsidian vault
* or chain subsequent copy jobs off them

---

## 4.2 Ecosystem expansion simulator (podcast/event/merch/sub-label evaluation)

This is a strategic scoring job type:

* inputs: the concept proposal
* doctrine: Ecosystem_Map + Cultural_Context + Positioning
* output: scores, risks, opportunities, and “recommended next actions”

If you want “revenue potential,” be careful:

* either keep it qualitative (low/med/high + rationale)
* or formalize assumptions as inputs so the run is auditable and not hand-wavy

---

## 4.3 Artist portfolio governance (overlap detection, roster gaps)

This is one of the few areas that benefits from **structured corpus**:

* roster manifests per artist (genres, archetype tags, sub-series fit)
* a single job can retrieve all roster docs (glob) or query for “archetype” (retrieve)

Output:

* overlap clusters
* missing archetypes
* recruitment targets
* recommended roster balance changes

---

# 5) CONTENT AT SCALE

## 5.1 Press & media automation

Ideal workflow:

* One job generates a press release “core”
* variants mode generates outlet-specific versions
* format mode produces:

  * `press_release_core.md`
  * `outlet_variants.json`
  * `pitch_emails.json`

Then chain compliance scoring on the versions.

## 5.2 Longform thought leadership

Same pattern:

* doctrine includes Manifesto + Cultural_Context
* output is deterministic essays and/or a “series plan”

To avoid low-grade repetition, you’ll want:

* a strong prompt template doctrine
* and deterministic constraints (outline-first, rhetorical devices, citations/claims policy inside doctrine)

---

# 6) OPERATIONAL WORKFLOWS

## 6.1 Job-based workflow engine

You already have the foundational model:

* Jobs are folders
* Pipelines are deterministic transforms
* Outputs are arbitrary artifacts, governed by manifest + snapshots

Your “productization” move is to define job types for:

* `GenerateReleaseNarrative`
* `BuildCampaignArc`
* `ScoreBrandCompliance`
* `EvaluateDemoFit`
* etc.

Each becomes:

* a pipeline module (`phase0_<job>.py`)
* a schema section in `schemas.py`
* smoke tests
* registry entry (routing)

## 6.2 Structured schema generation

This is exactly what `format` mode is for:

* generate `Release.yaml`
* generate `Artist.yaml`
* generate `Campaign.json`

Critical governance requirement:

* define stable output schemas (`v1.0.0.json` style)
* validate outputs at generation time (fail loud if invalid)

---

# 7) “CULTURAL WARFARE” USE CASES

These are still just deterministic jobs with aggressive doctrine.

## 7.1 Anti-algorithm positioning engine

Implementation pattern:

* scoring job flags forbidden phrases + clichés
* rewrite job generates “anti-algorithm” versions
* chain scoring again to verify improvement

## 7.2 Symbolic consistency validator

This is a validator job:

* inputs: visual prompt language / motifs / copy
* doctrine: Aesthetic_Framework + forbidden imagery list + sigil logic
* output: violations + suggested alternatives

## 7.3 Audience identity reinforcement

This becomes a generator job with constraints like:

* initiation language, tribe boundary signals, “exclusion without saying exclusion”
  …and then scored against doctrine so you don’t drift into cringe.

---

# 8) ADVANCED AI ORCHESTRATION

## 8.1 Multi-agent pipeline

You can implement multi-agent behavior **without nondeterminism** by using chainable stages:

* Stage A: Draft generation
* Stage B: Compliance scoring
* Stage C: Strategic alignment scoring
* Stage D: Intensifier rewrite
* Stage E: Final polish

Each stage is a job that consumes the prior artifact snapshot; each stage’s run_id deterministically reflects upstream outputs.

Key rule:

* downstream run must hash **prior output bytes** (Stage 8 pattern), not just prior manifest metadata.

## 8.2 Self-evolving doctrine

This is tricky governance-wise. If you do it:

* treat “doctrine updates” as explicit commits or versioned doctrine artifacts
* never silently update doctrine
* generate “doctrine change suggestions” as outputs, not automatic mutations

## 8.3 Predictive cultural modeling

Same as strategic simulator, but ensure:

* assumptions are explicitly input and snapshotted
* outputs are framed as scenarios, not facts

---

# 9) INTERNAL INTELLIGENCE

## 9.1 Decision brief generator

This is just a structured “decision packet” output job that aggregates:

* fit scores
* ecosystem impact
* risk
* recommendation
* evidence references (list the corpus items used, with hashes)

Retrieval mode is perfect here because it creates a clean evidence trail.

## 9.2 Release portfolio stress test

Requires:

* corpus of upcoming releases
* job loads them (glob/retrieve)
* outputs: fatigue risk, cannibalization risk, schedule recommendations

## 9.3 Long-term vision mapping

Best done as:

* a planning job that outputs a traceable mapping object:

  * vision → year → quarter → month → release → caption tags

Then downstream generation jobs reference those mapping artifacts (chainable) so you can prove traceability.

---

# 10) REVENUE EXPANSION

Merch/event/advisory are all:

* narrative generation + strategic scoring + compliance scoring
* optionally structured for Shopify / event platforms

---

# 11) META-LEVEL USE CASES

## Personal myth engineering / canonical timeline

Treat “canon” as a corpus domain:

* versioned myth docs
* timeline JSON
* any generated “new canon” proposals are outputs reviewed before being merged into doctrine/corpus

## Training corpus expansion

You can generate synthetic examples deterministically, but:

* treat them as artifacts
* track which doctrine version they came from
* never mix synthetic output into doctrine without explicit review

## Deterministic creative constraint mode

This is literally Stage 5 variants mode plus explicit constraint sets:

* minimalism constraint
* maximal occult density
* industrial aggression
  …and a scoring pass to quantify each dial.

---

# 12) How to implement the use cases you don’t yet have as pipelines

If a use case is not already a job type, the system expects you to create one in a very specific, deterministic way.

## Acceptance criteria for a new job type

A new pipeline is acceptable only if it:

1. Writes canonical snapshots first (`inputs/*.json`)
2. Computes `inputs_hash` only from snapshot file hashes
3. Derives `run_id` only from `inputs_hash` (+ deterministic suffix if needed)
4. Writes artifacts into `artifacts/<job_id>/<run_id>/...`
5. Writes a deterministic manifest (excluding nondeterministic observability fields)
6. Always remains reindexable/verifiable from filesystem alone
7. Adds smoke tests that prove:

   * idempotent replay
   * drift detection (input changes → run_id changes)
   * verify catches tampering

## Recommended “new job” template list

To realize the catalog cleanly, define these pipelines:

* `phase0_release_assets.py` (Beatport/Spotify/Bandcamp/press kit)
* `phase0_campaign_builder.py` (14-day arc output schema)
* `phase0_release_evaluator.py` (indices: mysticism/underground/aggression/authenticity)
* `phase0_ar_tool.py` (fit + sub-series placement + email drafts)
* `phase0_alignment_checker.py` (ecosystem coherence)
* `phase0_symbolic_validator.py` (motif compliance)
* `phase0_portfolio_governance.py` (roster balance and overlap)

Each one can share core infra, but must never break snapshot/run_id invariants.

---

# 13) Practical “recipes” for your highest-value SIGIL.ZERO workflows

## Recipe 1: Release caption pack + compliance

1. Run generator job in `variants` mode (e.g., 8 variants across tonal styles)
2. Run compliance scoring job chained to each chosen caption (or the whole pack)
3. Select final caption with evidence trail stored in artifacts

## Recipe 2: 14-day campaign arc

1. Generate `campaign_arc.json` in `format` mode
2. Generate per-platform posts (single or variants) referencing the arc artifact
3. Score compliance + strategic alignment for the whole plan

## Recipe 3: A&R decision packet

1. Evaluate demo fit (structured scoring output)
2. Generate acceptance/rejection email copy using doctrine
3. Produce `decision_brief.json` with references to all prior artifacts

## Recipe 4: Quarterly narrative architecture

1. Generate season arc artifact (structured)
2. Chain monthly releases to it
3. Enforce “no silent drift” by hashing prior outputs into downstream runs
