"""
LLM prompt templates for the Composio App Research Agent.

Contains carefully crafted prompts for:
- Stage 2: Classification (extract structured data from docs)
- Stage 3: Verification (independent re-check with different angle)
"""


# ─── STAGE 2: CLASSIFICATION PROMPT ─────────────────────────────────────────

CLASSIFICATION_PROMPT = """You are an API research analyst for Composio, a platform that turns SaaS apps
into tools that AI agents can call.

You are given scraped documentation for an app called "{app_name}" ({website}).
The app belongs to the "{category}" category.

Based ONLY on the documentation provided below, extract the following fields.
If the documentation does not contain enough information for a field, say
"not_found" rather than guessing.

DOCUMENTATION:
{docs_content}

MCP CHECK RESULTS:
{mcp_check}

RESPOND WITH ONLY THIS JSON (no markdown fences, no explanation, no commentary):
{{
  "one_liner": "<what this app does in ≤15 words>",
  "auth_methods": ["<OAuth2|API_Key|Basic|Bearer_Token|JWT|HMAC|Other|None>"],
  "auth_primary": "<the main/recommended auth method>",
  "auth_notes": "<any nuance about auth, or null>",
  "self_serve": <true|false>,
  "access_tier": "<free_tier|free_trial|paid_required|contact_sales|partner_gated|open_source>",
  "access_notes": "<detail on access, pricing tier needed, or null>",
  "api_type": ["<REST|GraphQL|SOAP|WebSocket|gRPC|CLI_Only|None>"],
  "api_breadth": "<narrow|moderate|broad>",
  "api_docs_quality": "<excellent|good|minimal|none>",
  "has_sdk": <true|false>,
  "sdk_languages": ["<language names or empty list>"],
  "has_webhooks": <true|false>,
  "has_rate_limits": <true|false>,
  "rate_limit_detail": "<specifics or null>",
  "has_existing_mcp": <true|false>,
  "mcp_source": "<URL or null>",
  "buildability": "<easy|moderate|hard|not_feasible>",
  "buildability_rationale": "<1-2 sentence explanation of why this buildability rating>",
  "main_blocker": "<primary blocker or null if easy>",
  "evidence_urls": ["<URLs from the docs used as evidence>"],
  "confidence": "<high|medium|low>"
}}

RULES:
- Base answers ONLY on the provided documentation, not general knowledge.
- "self_serve" = true means a developer can sign up and get API credentials
  without talking to a human, even if a paid plan is needed for API access.
- "buildability" considers: can Composio build an agent toolkit for this app
  TODAY? "easy" = self-serve auth + broad REST API + good docs.
  "moderate" = minor friction. "hard" = major friction. "not_feasible" = no API.
- If docs are missing/empty, set confidence to "low" and use "not_found" for unknown fields.
- For auth, list ALL methods mentioned in the docs, even if one is primary.
- For api_type, list ALL types the app supports.
- For buildability_rationale, be specific about what makes it easy/hard for Composio.
- Respond with ONLY valid JSON. No markdown code fences. No extra text."""


# ─── STAGE 3: VERIFICATION PROMPT ───────────────────────────────────────────

VERIFICATION_PROMPT = """You are a VERIFICATION agent. You are checking the accuracy of a research
agent's findings about the app "{app_name}" ({website}).

The research agent reported these findings:
- Auth methods: {agent_auth}
- Primary auth: {agent_auth_primary}
- Self-serve: {agent_self_serve}
- Access tier: {agent_access}
- API type: {agent_api_type}
- API breadth: {agent_api_breadth}
- Buildability: {agent_buildability}
- Has existing MCP: {agent_mcp}

Here is FRESH documentation scraped independently:
{fresh_docs}

For each field, verify whether the research agent's answer is correct based on
the fresh documentation. Respond with ONLY this JSON (no markdown, no explanation):

{{
  "auth_methods": {{
    "agree": <true|false>,
    "correct_value": "<if disagree, the correct value — otherwise same as agent>",
    "evidence": "<quote or reference from the docs supporting your answer>"
  }},
  "self_serve": {{
    "agree": <true|false>,
    "correct_value": <if disagree, true|false>,
    "evidence": "<quote or reference from the docs>"
  }},
  "access_tier": {{
    "agree": <true|false>,
    "correct_value": "<if disagree, the correct tier>",
    "evidence": "<quote or reference from the docs>"
  }},
  "api_type": {{
    "agree": <true|false>,
    "correct_value": "<if disagree, the correct types>",
    "evidence": "<quote or reference from the docs>"
  }},
  "api_breadth": {{
    "agree": <true|false>,
    "correct_value": "<if disagree, narrow|moderate|broad>",
    "evidence": "<quote or reference from the docs>"
  }},
  "buildability": {{
    "agree": <true|false>,
    "correct_value": "<if disagree, easy|moderate|hard|not_feasible>",
    "evidence": "<quote or reference from the docs>"
  }}
}}

RULES:
- Be STRICT. Only agree if the documentation clearly supports the agent's answer.
- If the fresh docs are ambiguous or missing, note that in the evidence field
  and default to agreeing with the agent (benefit of the doubt).
- Focus on factual accuracy, not stylistic differences.
- "self_serve" = true means a developer can independently sign up and get
  API credentials, even if payment is required.
- Respond with ONLY valid JSON. No markdown code fences."""


# ─── FALLBACK CLASSIFICATION PROMPT (for retry on parse failures) ────────────

CLASSIFICATION_RETRY_PROMPT = """The previous response was not valid JSON. Please try again.

For the app "{app_name}" ({website}), based on this documentation:
{docs_content}

Respond with ONLY a valid JSON object (no markdown fences, no explanation).
The JSON must have these exact keys:
one_liner, auth_methods, auth_primary, auth_notes, self_serve, access_tier,
access_notes, api_type, api_breadth, api_docs_quality, has_sdk, sdk_languages,
has_webhooks, has_rate_limits, rate_limit_detail, has_existing_mcp, mcp_source,
buildability, buildability_rationale, main_blocker, evidence_urls, confidence

Use "not_found" for any field you cannot determine from the docs.
Respond with ONLY the JSON object:"""


# ─── PATTERN ANALYSIS PROMPT (optional LLM-assisted insight generation) ──────

PATTERN_ANALYSIS_PROMPT = """You are a product strategy analyst for Composio, a platform that turns SaaS apps
into tools that AI agents can call.

You have data from researching 100 SaaS apps. Here are the aggregate statistics:

AUTH DISTRIBUTION:
{auth_stats}

ACCESS TIER DISTRIBUTION:
{access_stats}

BUILDABILITY BREAKDOWN:
{buildability_stats}

MCP COVERAGE:
{mcp_stats}

TOP BLOCKERS:
{blocker_stats}

CATEGORY BREAKDOWN:
{category_stats}

Based on this data, generate 5-8 sharp, non-obvious insights. Each insight should:
1. Have a specific, data-backed headline (include numbers)
2. State the implication for Composio's product roadmap
3. Be actionable — tell Composio what to do differently

Respond with ONLY a JSON array of insights:
[
  {{
    "headline": "<specific, data-backed headline with numbers>",
    "category": "<auth|access|buildability|mcp|blockers|strategy>",
    "implication": "<what this means for Composio's roadmap, 1-2 sentences>"
  }}
]

RULES:
- Be specific with numbers. Not "OAuth2 is common" but "OAuth2 at 62% vs API_Key at 28%".
- Every insight should lead to an ACTION for Composio.
- Include at least one insight about MCP whitespace (opportunity to be first).
- Include at least one insight about the "easy wins" vs "needs outreach" split.
- Respond with ONLY valid JSON. No markdown code fences."""
