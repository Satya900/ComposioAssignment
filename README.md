# Composio App Research Agent

AI-powered research pipeline that analyzes 100 SaaS apps for API surface,
authentication, access models, and agent-toolkit buildability.

## 🔗 Live Deliverable
[View the Research Report](https://composio-research.vercel.app)

## Quick Start

### Prerequisites
- Python 3.11+
- API keys: Groq (required for the main LLM path), Firecrawl (recommended), Composio (optional), GitHub Token (optional)

### Setup
```bash
git clone https://github.com/Satya900/composio-app-research.git
cd composio-app-research
pip install -r requirements.txt
cp .env.example .env  # Add your API keys
```

### Run the Agent
```bash
# Full pipeline: research -> classify -> verify -> patterns -> HTML (all 100 apps)
python -m agent.main

# Pilot run (5 apps, to sanity-check before spending the full budget)
python -m agent.main --pilot
```

In practice, free-tier LLM quotas (Groq's daily cap, OpenRouter's rate limits)
don't reliably clear 100 apps in one pass, so the pipeline is resumable via
a few one-off scripts that reuse whatever's already on disk instead of
re-running earlier stages from scratch:

```bash
# Resume Stage 2 classification for whatever's in data/classified/failures_v1.json
python retry_failed.py

# Stage 1b: look up all 100 apps against Composio's own toolkit catalog
python -m agent.composio_lookup

# Run Stage 3 verification (incl. the Composio catalog cross-check) +
# regenerate the HTML report against the completed results_v1.json
python run_verification.py

# If the re-verification step (confirming corrections) got hit by provider
# exhaustion mid-run, re-check just the corrected apps + a fresh sample
# instead of redoing Layer 1 + the first-pass Layer 2 that already succeeded
python reverify_corrections.py

# Regenerate patterns + HTML only, without re-running verification
python finalize_report.py
```

## Architecture

```
Stage 1: Web Research     → Firecrawl + direct HTTP (docs), GitHub/npm MCP check
Stage 1b: Composio Lookup → Composio SDK's own toolkit catalog (real ground truth)
Stage 2: LLM Classify     → Groq (temp=0, structured JSON), OpenRouter fallback
Stage 3: Verification     → 3-layer (auto incl. Composio catalog + agent + human)
Stage 4: Pattern Analysis → 8 dimensions, 8 insights
Output:  HTML Case Study  → Single page, deployed to Vercel
```

## Pipeline Stages

### Stage 1: Web Research
For each app, the agent searches for developer documentation, scrapes the most relevant pages via Firecrawl + direct HTTP, and checks for existing MCP servers (via GitHub and npm).

### Stage 1b: Composio SDK — Toolkit Catalog Lookup
`agent/composio_lookup.py` queries **Composio's own toolkit catalog** via the current `composio` SDK for all 100 apps — first-party ground truth on real auth modes and tool counts for whatever Composio has already built, independent of anything scraped or LLM-inferred. 50/100 researched apps already exist as Composio toolkits. This data feeds two places downstream:
- **Stage 3 Layer 1** — flags a result if it disagrees with Composio's own catalog (e.g. `buildability=not_feasible` claimed for an app Composio already has a working toolkit for)
- **Stage 4 Pattern Analysis** — the "Composio Catalog Coverage" insight separates apps Composio has already built from the actual net-new opportunity

(Note: the *current* `composio` SDK doesn't expose a generic "search the web"/"scrape a URL" action — that lived in the deprecated `composio-core`/`ComposioToolSet` API this project no longer uses — so Composio SDK isn't part of Stage 1's docs-scraping path; it's used for what it's actually good for, its own catalog.)

### Stage 2: LLM Classification
Raw documentation is fed to Groq (falling back to OpenRouter's free tier when Groq's daily quota is exhausted) with a structured extraction prompt. The model outputs JSON covering auth methods, access tiers, API surface, buildability, and more. A taxonomy-normalization layer coerces synonym/casing variants from the weaker fallback model onto canonical values before validation.

### Stage 3: Verification (Most Critical)
- **Layer 1:** Automated cross-check — logical consistency rules, evidence URL validation, known-good reference data, and Composio's own catalog
- **Layer 2:** Verification agent — independent LLM call with fresh docs + different prompt angle
- **Layer 3:** Human spot-check — manual verification checklist for ~12 apps across all categories
- **Correction loop:** Apply fixes (validated against the taxonomy before writing), re-verify, document accuracy improvement

### Stage 4: Pattern Analysis
Transforms 100 individual results into cross-cutting insights across 8 dimensions: auth distribution, self-serve vs gated, buildability scorecard, common blockers, MCP landscape, strategic prioritization, docs-quality correlation, and Composio catalog coverage (already-built vs net-new).

## Accuracy
Three-layer verification against the completed 100-app run:
- **Layer 1** (automated cross-check, all 100 apps — logic rules, known-good reference data, Composio's own catalog, evidence URL reachability): 29 apps flagged, 45 issues
- **Layer 2** (independent LLM re-check, 52-app sample: 25 random + 27 flagged): **84.1% first-pass accuracy**
- **Correction loop**: 26 corrections applied (each validated against the taxonomy before being written back — a proposed "correction" that didn't map to a valid enum value, or a list-typed field, was discarded/reshaped rather than applied as-is)
- **Re-verification**: **90.9% final accuracy** (+6.8%), 66 fields checked across the apps that got a real re-check
- **Layer 3** (human spot-check): checklist generated at `data/verification/human_checklist.md`, ~12 apps across all 10 categories, for manual doc cross-checking

Per-field accuracy on the final pass: self_serve/api_type/api_breadth/buildability all 100%, access_tier 90.9%, **auth_methods 54.5%** — auth is consistently the field the verifier disagrees with most, since apps often support more auth methods than a single docs page mentions.

A methodology note worth being upfront about: the verification LLM frequently sets `agree=False` while its own evidence says "no information found" in the fresh docs it was given (a 2-page/6000-char excerpt) — that's the verifier's context limitation, not necessarily the original agent being wrong. `agent/verifier.py` treats an inconclusive-evidence disagreement, or a "disagreement" where the verifier's own correct_value is equivalent to the agent's, as agreement rather than an error — otherwise the accuracy score would mostly measure the verifier's context window rather than the agent's correctness.

Full breakdown (per-field accuracy, error patterns, every correction with old→new value) is in `data/verification/` and rendered in the report's Verification & Accuracy section.

## Known Limitations
- **fanbasis, higgsfield**: minimal public API docs; classified `hard`/`moderate` buildability on low-confidence, best-effort evidence
- **PitchBook, DealCloud**: not paid-account-blocked as originally assumed — both classified successfully (`moderate` buildability) once verification caught and corrected the first pass. Real blocker is non-self-serve signup / admin-provisioned credentials, not missing docs
- **Sherlock, Mermaid CLI**: correctly classified as CLI tools rather than SaaS APIs (`api_type: CLI_Only`), with correspondingly thin "API surface" data
- MCP existence check may miss unofficial/private MCP servers not indexed on GitHub/npm
- The free OpenRouter fallback model (used once Groq's daily quota is exhausted) doesn't reliably honor strict JSON-schema output — the pipeline compensates with a taxonomy-normalization layer (`agent/classifier.py::_normalize_taxonomy`) that maps synonym/casing variants (e.g. `"api_key"` → `"API_Key"`, `"wide"` → `"broad"`) onto canonical values, but a small number of apps still needed a second classification pass to converge

## Built With
- [Composio SDK](https://composio.dev) — Optional research-tool integration
- [Groq](https://console.groq.com/docs/openai) — Structured extraction and verification
- [Firecrawl](https://firecrawl.dev) — Fallback docs scraping
- [Chart.js](https://chartjs.org) + [Tailwind CSS](https://tailwindcss.com) — HTML report visualization

## Author
**Satyabrata Mohanty** — AI Product Ops Take-Home Assignment, July 2026
