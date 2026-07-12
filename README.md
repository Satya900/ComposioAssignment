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

# Run Stage 3 verification + regenerate the HTML report against the
# completed data/classified/results_v1.json (reuses cached Stage 1 docs)
python run_verification.py

# Regenerate patterns + HTML only, without re-running verification
python finalize_report.py
```

## Architecture

```
Stage 1: Web Research    → Firecrawl + HTTP fallback (Composio SDK when compatible)
Stage 2: LLM Classify    → Groq OpenAI-compatible model (temp=0, structured JSON)
Stage 3: Verification    → 3-layer (auto + agent + human)
Stage 4: Pattern Analysis → 6 dimensions, 5-8 insights
Output:  HTML Case Study  → Single page, deployed to Vercel
```

## Pipeline Stages

### Stage 1: Web Research
For each app, the agent searches for developer documentation, scrapes the most relevant pages, and checks for existing MCP servers (via GitHub and npm).

### Stage 2: LLM Classification
Raw documentation is fed to the configured Groq model with a structured extraction prompt. The model outputs JSON covering auth methods, access tiers, API surface, buildability, and more.

### Stage 3: Verification (Most Critical)
- **Layer 1:** Automated cross-check — logical consistency rules + evidence URL validation
- **Layer 2:** Verification agent — independent LLM call with fresh docs + different prompt angle
- **Layer 3:** Human spot-check — manual browser verification of 10-15 apps
- **Correction loop:** Apply fixes, re-verify, document accuracy improvement

### Stage 4: Pattern Analysis
Transforms 100 individual results into cross-cutting insights across 6 dimensions: auth distribution, self-serve vs gated, buildability scorecard, common blockers, MCP landscape, and strategic prioritization.

## Accuracy
Three-layer verification against the completed 100-app run:
- **Layer 1** (automated cross-check, all 100 apps): 20 apps flagged, 29 logical-consistency/evidence-URL issues
- **Layer 2** (independent LLM re-check, 45-app sample: 25 random + 20 flagged): **89.4% first-pass accuracy**
- **Correction loop**: 12 corrections applied (each validated against the taxonomy before being written back — a proposed "correction" that didn't map to a valid enum value was discarded rather than applied)
- **Re-verification** (23-app sample after corrections): **91.7% final accuracy** (+2.3%)
- **Layer 3** (human spot-check): checklist generated at `data/verification/human_checklist.md`, ~12 apps across all 10 categories, for manual doc cross-checking

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
