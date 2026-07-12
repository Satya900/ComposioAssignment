"""
Pydantic models and enums for the Composio App Research Agent.

Defines all data structures used across the pipeline:
- Input schemas (AppInput)
- Core output schemas (AppResearchResult)
- Verification schemas (FieldVerification, AppVerification, AccuracyReport)
- Pattern analysis schemas (PatternInsight, PatternReport)
- All enums (AuthMethod, AccessTier, APIType, etc.)
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── ENUMS ───────────────────────────────────────────────────────────────────


class AuthMethod(str, Enum):
    OAUTH2 = "OAuth2"
    API_KEY = "API_Key"
    BASIC = "Basic"
    TOKEN = "Bearer_Token"
    JWT = "JWT"
    HMAC = "HMAC"
    OTHER = "Other"
    NONE = "None"


class AccessTier(str, Enum):
    FREE_TIER = "free_tier"            # Free forever plan with API access
    FREE_TRIAL = "free_trial"          # Time-limited trial
    PAID_REQUIRED = "paid_required"    # Must pay, but self-serve
    CONTACT_SALES = "contact_sales"    # Enterprise/sales-gated
    PARTNER_GATED = "partner_gated"    # Requires partnership agreement
    OPEN_SOURCE = "open_source"        # OSS, run your own


class APIType(str, Enum):
    REST = "REST"
    GRAPHQL = "GraphQL"
    SOAP = "SOAP"
    WEBSOCKET = "WebSocket"
    GRPC = "gRPC"
    CLI_ONLY = "CLI_Only"
    NONE = "None"


class APIBreadth(str, Enum):
    NARROW = "narrow"        # <20 endpoints
    MODERATE = "moderate"    # 20-100 endpoints
    BROAD = "broad"          # 100+ endpoints


class DocsQuality(str, Enum):
    EXCELLENT = "excellent"  # Interactive docs, examples, SDKs
    GOOD = "good"            # Complete reference docs
    MINIMAL = "minimal"      # Basic docs, missing examples
    NONE = "none"            # No public API docs found


class Buildability(str, Enum):
    EASY = "easy"                # Self-serve + broad API + good docs → build today
    MODERATE = "moderate"        # Minor friction (paid tier, limited endpoints)
    HARD = "hard"                # Major friction (sales-gated, poor docs, auth complexity)
    NOT_FEASIBLE = "not_feasible"  # No API, or fully partner-locked


class Confidence(str, Enum):
    HIGH = "high"      # Verified against official docs
    MEDIUM = "medium"  # Agent-extracted, plausible but unverified
    LOW = "low"        # Incomplete data, guesses involved


# ─── INPUT SCHEMA ────────────────────────────────────────────────────────────


class AppInput(BaseModel):
    """Input schema for a single app to research."""
    id: int = Field(..., description="App ID (1-100)")
    name: str = Field(..., description="App name, e.g. 'Salesforce'")
    website: str = Field(..., description="Website URL hint, e.g. 'salesforce.com'")
    category: str = Field(..., description="Category, e.g. 'CRM and Sales'")
    docs_url: Optional[str] = Field(None, description="Discovered docs URL (filled by agent)")


# ─── CORE OUTPUT SCHEMA ─────────────────────────────────────────────────────


class AppResearchResult(BaseModel):
    """Core output schema for a single app's research result."""

    # Identity
    id: int
    name: str
    website: str
    category: str
    one_liner: str = Field(default="", description="What it does, ≤15 words")

    # Auth
    auth_methods: List[str] = Field(default_factory=list, description="Auth methods: OAuth2, API_Key, Basic, Bearer_Token, JWT, HMAC, Other, None")
    auth_primary: str = Field(default="", description="The dominant/recommended auth method")
    auth_notes: Optional[str] = Field(None, description="Nuance about auth approach")

    # Access Model
    self_serve: bool = Field(default=False, description="Can a dev get credentials without human gatekeeping?")
    access_tier: str = Field(default="", description="free_tier, free_trial, paid_required, contact_sales, partner_gated, open_source")
    access_notes: Optional[str] = Field(None, description="Detail on access, pricing tier needed")

    # API Surface
    api_type: List[str] = Field(default_factory=list, description="REST, GraphQL, SOAP, WebSocket, gRPC, CLI_Only, None")
    api_breadth: str = Field(default="", description="narrow (<20 endpoints), moderate (20-100), broad (100+)")
    api_docs_quality: str = Field(default="", description="excellent, good, minimal, none")
    has_sdk: bool = Field(default=False, description="Official SDK available?")
    sdk_languages: List[str] = Field(default_factory=list, description="SDK languages available")
    has_webhooks: bool = Field(default=False, description="Supports webhook/event subscriptions?")
    has_rate_limits: bool = Field(default=False, description="Documented rate limits?")
    rate_limit_detail: Optional[str] = Field(None, description="Rate limit specifics")

    # MCP & Agent Readiness
    has_existing_mcp: bool = Field(default=False, description="Known MCP server exists?")
    mcp_source: Optional[str] = Field(None, description="URL to MCP server if exists")
    buildability: str = Field(default="", description="easy, moderate, hard, not_feasible")
    buildability_rationale: str = Field(default="", description="1-2 sentence explanation")
    main_blocker: Optional[str] = Field(None, description="Primary blocker if not 'easy'")

    # Evidence
    evidence_urls: List[str] = Field(default_factory=list, description="Docs URLs backing the answers")
    confidence: str = Field(default="medium", description="high, medium, low")
    research_method: str = Field(default="agent_automated", description="agent_automated | agent_plus_human | manual_only")
    notes: Optional[str] = Field(None, description="Edge cases, gotchas, special observations")

    # Metadata
    researched_at: Optional[str] = Field(None, description="ISO timestamp of research")
    verified: bool = Field(default=False, description="Has been through verification?")
    verified_at: Optional[str] = Field(None, description="ISO timestamp of verification")


# ─── VERIFICATION SCHEMAS ───────────────────────────────────────────────────


class FieldVerification(BaseModel):
    """Verification result for a single field of a single app."""
    field_name: str = Field(..., description="Field name, e.g. 'auth_methods'")
    agent_value: Any = Field(..., description="What the agent reported")
    actual_value: Any = Field(..., description="What the verifier found")
    is_correct: bool = Field(..., description="Whether agent was correct")
    evidence_url: str = Field(default="", description="URL proving the correct answer")
    notes: Optional[str] = Field(None, description="Explanation of disagreement")


class AppVerification(BaseModel):
    """Verification result for a single app across multiple fields."""
    app_id: int
    app_name: str
    fields_checked: List[FieldVerification]
    overall_correct: int = Field(0, description="Count of correct fields")
    overall_total: int = Field(0, description="Total fields checked")
    accuracy_pct: float = Field(0.0, description="Per-app accuracy percentage")
    verified_by: str = Field(default="verification_agent", description="verification_agent | human | both")


class AccuracyReport(BaseModel):
    """Aggregate accuracy report across all verified apps."""
    sample_size: int = Field(0, description="Number of apps in verified sample")
    total_fields_checked: int = Field(0)
    total_correct: int = Field(0)
    overall_accuracy: float = Field(0.0, description="Overall accuracy percentage")
    per_field_accuracy: Dict[str, float] = Field(default_factory=dict, description="Per-field accuracy, e.g. {'auth_methods': 90.0}")
    first_pass_accuracy: float = Field(0.0, description="Accuracy before corrections")
    final_accuracy: float = Field(0.0, description="Accuracy after verification loop")
    improvement_delta: float = Field(0.0, description="final - first_pass")
    common_error_patterns: List[str] = Field(default_factory=list, description="What the agent gets wrong")
    app_verifications: List[AppVerification] = Field(default_factory=list)


# ─── PATTERN ANALYSIS SCHEMAS ───────────────────────────────────────────────


class PatternInsight(BaseModel):
    """A single cross-cutting insight derived from the 100-app dataset."""
    headline: str = Field(..., description="Sharp headline, e.g. 'OAuth2 dominates at 62%...'")
    category: str = Field(..., description="auth | access | buildability | mcp | blockers | strategy")
    supporting_data: Dict[str, Any] = Field(default_factory=dict, description="Raw numbers backing the claim")
    affected_apps: List[str] = Field(default_factory=list, description="App names relevant to this pattern")
    implication: str = Field(default="", description="What this means for Composio's roadmap")


class PatternReport(BaseModel):
    """Complete pattern analysis report across all 100 apps."""
    insights: List[PatternInsight] = Field(default_factory=list, description="5-8 insights")
    auth_distribution: Dict[str, int] = Field(default_factory=dict, description="{'OAuth2': 62, 'API_Key': 28, ...}")
    access_distribution: Dict[str, int] = Field(default_factory=dict, description="{'free_tier': 35, 'paid_required': 25, ...}")
    buildability_by_category: Dict[str, Dict[str, int]] = Field(default_factory=dict, description="{'CRM': {'easy': 4, ...}}")
    mcp_coverage: Dict[str, Any] = Field(default_factory=dict, description="MCP landscape data")
    top_blockers: List[Dict[str, Any]] = Field(default_factory=list, description="Ranked blockers list")
    easy_wins: List[str] = Field(default_factory=list, description="Apps ready to build today")
    needs_outreach: List[str] = Field(default_factory=list, description="Apps requiring partnership/sales contact")


# ─── RAW RESEARCH DATA ──────────────────────────────────────────────────────


class RawResearchData(BaseModel):
    """Raw scraped documentation data for a single app (Stage 1 output)."""
    app_name: str
    website: str
    docs_pages: List[Dict[str, str]] = Field(default_factory=list, description="[{'url': ..., 'content': ...}]")
    mcp_check: Dict[str, Any] = Field(default_factory=dict, description="MCP existence check results")
    research_method: str = Field(default="composio_sdk", description="composio_sdk | firecrawl_fallback | manual")
    research_timestamp: str = Field(default="")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered during research")
