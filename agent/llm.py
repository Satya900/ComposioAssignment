"""Shared LLM client helper."""

import logging
import time
from typing import Any, Dict, List, Tuple

from openai import OpenAI

from agent.config import LLM_API_KEY, LLM_BASE_URL, LLM_PROVIDER, LLM_PROVIDER_CHAIN

logger = logging.getLogger("composio-research")


CLASSIFICATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "one_liner": {"type": "string"},
        "auth_methods": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "OAuth2",
                    "API_Key",
                    "Basic",
                    "Bearer_Token",
                    "JWT",
                    "HMAC",
                    "Other",
                    "None",
                    "not_found",
                ],
            },
        },
        "auth_primary": {
            "type": "string",
            "enum": [
                "OAuth2",
                "API_Key",
                "Basic",
                "Bearer_Token",
                "JWT",
                "HMAC",
                "Other",
                "None",
                "not_found",
            ],
        },
        "auth_notes": {"type": ["string", "null"]},
        "self_serve": {"type": "boolean"},
        "access_tier": {
            "type": "string",
            "enum": [
                "free_tier",
                "free_trial",
                "paid_required",
                "contact_sales",
                "partner_gated",
                "open_source",
                "not_found",
            ],
        },
        "access_notes": {"type": ["string", "null"]},
        "api_type": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "REST",
                    "GraphQL",
                    "SOAP",
                    "WebSocket",
                    "gRPC",
                    "CLI_Only",
                    "None",
                    "not_found",
                ],
            },
        },
        "api_breadth": {
            "type": "string",
            "enum": ["narrow", "moderate", "broad", "not_found"],
        },
        "api_docs_quality": {
            "type": "string",
            "enum": ["excellent", "good", "minimal", "none", "not_found"],
        },
        "has_sdk": {"type": "boolean"},
        "sdk_languages": {"type": "array", "items": {"type": "string"}},
        "has_webhooks": {"type": "boolean"},
        "has_rate_limits": {"type": "boolean"},
        "rate_limit_detail": {"type": ["string", "null"]},
        "has_existing_mcp": {"type": "boolean"},
        "mcp_source": {"type": ["string", "null"]},
        "buildability": {
            "type": "string",
            "enum": ["easy", "moderate", "hard", "not_feasible", "not_found"],
        },
        "buildability_rationale": {"type": "string"},
        "main_blocker": {"type": ["string", "null"]},
        "evidence_urls": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low", "not_found"],
        },
    },
    "required": [
        "one_liner",
        "auth_methods",
        "auth_primary",
        "auth_notes",
        "self_serve",
        "access_tier",
        "access_notes",
        "api_type",
        "api_breadth",
        "api_docs_quality",
        "has_sdk",
        "sdk_languages",
        "has_webhooks",
        "has_rate_limits",
        "rate_limit_detail",
        "has_existing_mcp",
        "mcp_source",
        "buildability",
        "buildability_rationale",
        "main_blocker",
        "evidence_urls",
        "confidence",
    ],
    "additionalProperties": False,
}

VERIFICATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "auth_methods": {
            "type": "object",
            "properties": {
                "agree": {"type": "boolean"},
                "correct_value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "boolean"},
                        {"type": "null"},
                    ]
                },
                "evidence": {"type": "string"},
            },
            "required": ["agree", "correct_value", "evidence"],
            "additionalProperties": False,
        },
        "self_serve": {
            "type": "object",
            "properties": {
                "agree": {"type": "boolean"},
                "correct_value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "boolean"},
                        {"type": "null"},
                    ]
                },
                "evidence": {"type": "string"},
            },
            "required": ["agree", "correct_value", "evidence"],
            "additionalProperties": False,
        },
        "access_tier": {
            "type": "object",
            "properties": {
                "agree": {"type": "boolean"},
                "correct_value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ]
                },
                "evidence": {"type": "string"},
            },
            "required": ["agree", "correct_value", "evidence"],
            "additionalProperties": False,
        },
        "api_type": {
            "type": "object",
            "properties": {
                "agree": {"type": "boolean"},
                "correct_value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ]
                },
                "evidence": {"type": "string"},
            },
            "required": ["agree", "correct_value", "evidence"],
            "additionalProperties": False,
        },
        "api_breadth": {
            "type": "object",
            "properties": {
                "agree": {"type": "boolean"},
                "correct_value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
                "evidence": {"type": "string"},
            },
            "required": ["agree", "correct_value", "evidence"],
            "additionalProperties": False,
        },
        "buildability": {
            "type": "object",
            "properties": {
                "agree": {"type": "boolean"},
                "correct_value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
                "evidence": {"type": "string"},
            },
            "required": ["agree", "correct_value", "evidence"],
            "additionalProperties": False,
        },
    },
    "required": [
        "auth_methods",
        "self_serve",
        "access_tier",
        "api_type",
        "api_breadth",
        "buildability",
    ],
    "additionalProperties": False,
}


def create_llm_client() -> OpenAI:
    if not LLM_API_KEY:
        raise RuntimeError(f"{LLM_PROVIDER.upper()} API key is not configured")

    return OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
    )


# Groq's strict `json_schema` structured-output mode is only supported by
# a subset of models (currently the gpt-oss family). Other models (e.g.
# llama-3.3-70b-versatile) reject that response_format with a 400. Fall back
# to plain json_object for those — the taxonomy-validation retry loop in
# classifier.py already handles the looser output that mode produces.
_STRUCTURED_OUTPUT_MODEL_MARKERS = ("gpt-oss",)


def response_format_for(stage: str, provider: str = LLM_PROVIDER, model: str = "") -> dict:
    supports_strict_schema = provider == "groq" and (
        not model or any(marker in model for marker in _STRUCTURED_OUTPUT_MODEL_MARKERS)
    )
    if supports_strict_schema:
        schema = CLASSIFICATION_RESPONSE_SCHEMA if stage == "classification" else VERIFICATION_RESPONSE_SCHEMA
        return {
            "type": "json_schema",
            "json_schema": {
                "name": f"{stage}_schema",
                "strict": True,
                "schema": schema,
            },
        }

    return {"type": "json_object"}


# ─── MULTI-PROVIDER FAILOVER ─────────────────────────────────────────────────
#
# Free-tier LLM quotas (e.g. Groq's daily token cap) get exhausted mid-run on
# 100 sequential calls. Rather than let every remaining app fail once that
# happens, walk LLM_PROVIDER_CHAIN and move on to the next configured
# provider — remembering which ones are exhausted so we don't keep retrying
# a dead provider on every subsequent app.

_clients: Dict[str, OpenAI] = {}
_exhausted_providers: set = set()

_RATE_LIMIT_MARKERS = ("rate_limit", "429", "quota", "tokens per day", "tpm", "tpd")
# A per-minute throttle recovers in seconds; a daily cap doesn't. These
# markers distinguish the two so we don't burn a whole provider over what
# is really just "wait a moment and retry".
_DAILY_CAP_MARKERS = ("tokens per day", "tpd", "per day")
_BACKOFF_SECONDS = (10, 25)


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)


def _is_daily_cap_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _DAILY_CAP_MARKERS)


def _client_for(cfg: Dict[str, Any]) -> OpenAI:
    provider = cfg["provider"]
    if provider not in _clients:
        _clients[provider] = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    return _clients[provider]


def chat_completion_with_failover(
    *, messages: List[Dict[str, str]], max_tokens: int, temperature: float, stage: str
) -> Tuple[Any, str]:
    """
    Try each provider in LLM_PROVIDER_CHAIN in order, skipping any already
    known to be exhausted. Returns (response, provider_used). Raises the
    last error if every provider fails.
    """
    last_error: Exception | None = None

    for cfg in LLM_PROVIDER_CHAIN:
        provider = cfg["provider"]
        if provider in _exhausted_providers:
            continue

        client = _client_for(cfg)

        # Give a rate-limited provider a couple of short backoff-retries —
        # most 429s here are per-minute throttles that clear in seconds, not
        # the hard daily cap. Only mark the provider exhausted (skipped for
        # the rest of the run) once retries on it are also rate-limited AND
        # the error itself looks like a daily/hard cap, or retries run out.
        attempts = list(_BACKOFF_SECONDS) + [None]  # None = final attempt, no more waiting after
        for attempt_index, backoff in enumerate(attempts):
            try:
                response = client.chat.completions.create(
                    model=cfg["model"],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format=response_format_for(stage, provider, cfg["model"]),
                    messages=messages,
                )
                return response, provider
            except Exception as e:
                last_error = e
                if not _is_rate_limit_error(e):
                    raise

                if _is_daily_cap_error(e) or backoff is None:
                    logger.warning(
                        f"{provider} rate-limited ({'daily cap' if _is_daily_cap_error(e) else 'retries exhausted'}) "
                        f"— marking exhausted and switching to the next configured provider"
                    )
                    _exhausted_providers.add(provider)
                    break

                logger.warning(
                    f"{provider} hit a transient rate limit — waiting {backoff}s "
                    f"and retrying (attempt {attempt_index + 1}/{len(attempts) - 1})"
                )
                time.sleep(backoff)
        # provider exhausted or all backoff attempts used — fall through to next provider

    raise last_error or RuntimeError("No LLM provider configured")
