"""
Configuration and settings for the Composio App Research Agent.

Loads API keys from .env and defines all pipeline constants.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ─── PROJECT PATHS ───────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
RAW_DIR = DATA_DIR / "raw"
CLASSIFIED_DIR = DATA_DIR / "classified"
VERIFICATION_DIR = DATA_DIR / "verification"
FINAL_DIR = DATA_DIR / "final"
SITE_DIR = PROJECT_ROOT / "site"

# Ensure data directories exist
for d in [RAW_DIR, CLASSIFIED_DIR, VERIFICATION_DIR, FINAL_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ─── API KEYS ────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "")
COMPOSIO_USER_ID = os.getenv("COMPOSIO_USER_ID", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


# ─── LLM CONFIGURATION ──────────────────────────────────────────────────────

LLM_PROVIDER = os.getenv(
    "LLM_PROVIDER",
    "groq" if GROQ_API_KEY else "openrouter",
).strip().lower()

if LLM_PROVIDER == "groq":
    LLM_API_KEY = GROQ_API_KEY
    LLM_BASE_URL = "https://api.groq.com/openai/v1"
    MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
else:
    LLM_PROVIDER = "openrouter"
    LLM_API_KEY = OPENROUTER_API_KEY
    LLM_BASE_URL = "https://openrouter.ai/api/v1"
    MODEL_NAME = os.getenv("OPENROUTER_MODEL", "tencent/hy3:free")

# Ordered failover chain: primary provider first, then whichever others have
# a configured key. When a provider's call fails with a rate-limit/quota
# error (e.g. Groq's daily token cap), the next one in the chain is used for
# the rest of the run instead of failing the app outright.
_GROQ_CFG = {
    "provider": "groq",
    "api_key": GROQ_API_KEY,
    "base_url": "https://api.groq.com/openai/v1",
    "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
}
_OPENROUTER_CFG = {
    "provider": "openrouter",
    "api_key": OPENROUTER_API_KEY,
    "base_url": "https://openrouter.ai/api/v1",
    "model": os.getenv("OPENROUTER_MODEL", "tencent/hy3:free"),
}
_ALL_PROVIDER_CFGS = [_GROQ_CFG, _OPENROUTER_CFG]
LLM_PROVIDER_CHAIN = [
    cfg
    for cfg in sorted(_ALL_PROVIDER_CFGS, key=lambda c: c["provider"] != LLM_PROVIDER)
    if cfg["api_key"]
]

CLASSIFICATION_MAX_TOKENS = 2500
VERIFICATION_MAX_TOKENS = 2000
TEMPERATURE = 0  # Deterministic for consistency


# ─── PIPELINE CONSTANTS ─────────────────────────────────────────────────────

# Research stage
RESEARCH_CONCURRENCY = int(os.getenv("RESEARCH_CONCURRENCY", "5"))
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "3"))
RETRY_DELAY_BASE = 2  # Exponential backoff base (seconds)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
SCRAPE_MAX_TOKENS = int(os.getenv("SCRAPE_MAX_TOKENS", "4000"))

# Classification stage
CLASSIFICATION_BATCH_SIZE = 5
CLASSIFICATION_BATCH_DELAY = 1  # Seconds between batches

# Verification stage
VERIFICATION_SAMPLE_SIZE = int(os.getenv("VERIFICATION_SAMPLE_SIZE", "25"))
HUMAN_CHECK_TARGET = 12  # Target number of apps for human verification

# Checkpoint frequency
CHECKPOINT_EVERY_N = 10  # Save results every N apps

# Maximum docs content per app sent to LLM (in characters)
MAX_DOCS_CONTENT_CHARS = 8000


# ─── KNOWN-GOOD GROUND TRUTH ────────────────────────────────────────────────
# Used in automated cross-checks (Layer 1 verification).
# These are well-known apps where we can hardcode the correct answers.

KNOWN_APPS = {
    "GitHub": {
        "auth": ["OAuth2", "Bearer_Token"],
        "api": ["REST", "GraphQL"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Slack": {
        "auth": ["OAuth2"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Stripe": {
        "auth": ["API_Key"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Salesforce": {
        "auth": ["OAuth2"],
        "api": ["REST", "SOAP"],
        "self_serve": False,
        "api_breadth": "broad",
    },
    "Shopify": {
        "auth": ["OAuth2", "API_Key"],
        "api": ["REST", "GraphQL"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Notion": {
        "auth": ["OAuth2", "Bearer_Token"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "moderate",
    },
    "Discord": {
        "auth": ["OAuth2", "Bearer_Token"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Twilio": {
        "auth": ["Basic"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "HubSpot": {
        "auth": ["OAuth2", "API_Key"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Zendesk": {
        "auth": ["OAuth2", "API_Key", "Basic"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Jira": {
        "auth": ["OAuth2", "Basic", "API_Key"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "broad",
    },
    "Airtable": {
        "auth": ["OAuth2", "Bearer_Token"],
        "api": ["REST"],
        "self_serve": True,
        "api_breadth": "moderate",
    },
}


# ─── APP-SPECIFIC RESEARCH STRATEGIES ───────────────────────────────────────
# For apps that are known to be tricky, define special strategies.

PROBLEM_APPS = {
    "fanbasis": "Likely no public API. Search thoroughly, mark as no_public_api with evidence.",
    "Paygent Connect": "NMI-powered. Research NMI's API as parent platform.",
    "iPayX": "Minimal docs. Check ipayx.ai/docs, mark minimal_docs if empty.",
    "Sherlock": "CLI tool (Python library), not a SaaS API. Classify as CLI_Only.",
    "Mermaid CLI": "CLI/npm package, not a web API. Classify as CLI_Only.",
    "higgsfield": "CLI-based content tool. Check for API behind CLI.",
    "systeme.io": "Funnel builder. May not have public API.",
    "Waterfall.io": "Data intel. Likely contact_sales or partner_gated.",
    "PitchBook": "Enterprise-only research API. Likely contact_sales.",
    "DealCloud": "Intapp product, likely gated. Check api.docs.dealcloud.com.",
    "NotebookLM": "Google/Gemini, unclear API status. Check Enterprise API.",
    "Consensus": "OAuth requested, unclear status. Mark as emerging.",
    "Gladly": "Enterprise support. Likely contact_sales.",
}


# ─── LOGGING ─────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = PROJECT_ROOT / "agent.log"


# ─── CATEGORIES (exact names from assignment) ───────────────────────────────

CATEGORIES = [
    "CRM and Sales",
    "Support and Helpdesk",
    "Communications and Messaging",
    "Marketing, Ads, Email and Social",
    "Ecommerce",
    "Data, SEO and Scraping",
    "Developer, Infra and Data platforms",
    "Productivity and Project Management",
    "Finance and Fintech",
    "AI, Research and Media-native",
]
