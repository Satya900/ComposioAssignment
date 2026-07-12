"""
Stage 2: LLM Classification Agent

Takes raw scraped documentation text and extracts structured data using
Claude Sonnet with a tightly constrained output schema.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.config import (
    CLASSIFICATION_BATCH_SIZE,
    CLASSIFICATION_BATCH_DELAY,
    CLASSIFICATION_MAX_TOKENS,
    CLASSIFIED_DIR,
    MAX_DOCS_CONTENT_CHARS,
    LLM_PROVIDER_CHAIN,
    TEMPERATURE,
    CHECKPOINT_EVERY_N,
)
from agent.prompts import CLASSIFICATION_PROMPT, CLASSIFICATION_RETRY_PROMPT
from agent.schemas import AppInput, AppResearchResult, RawResearchData
from agent.llm import chat_completion_with_failover
from agent.utils import (
    clean_text,
    extract_json_from_text,
    get_logger,
    now_iso,
    save_json,
    truncate_text,
)

logger = get_logger()


# ─── SINGLE APP CLASSIFICATION ──────────────────────────────────────────────


async def classify_single_app(
    app: AppInput,
    raw_data: RawResearchData,
) -> Tuple[Optional[AppResearchResult], Optional[Dict]]:
    """
    Classify a single app using Claude.
    Returns (result, None) on success or (None, error_dict) on failure.
    """
    app_name = app.name
    website = app.website
    category = app.category

    # Combine docs content, giving each page its own budget so an earlier
    # page (e.g. a marketing homepage) can't crowd out a later one that
    # actually has the answer (e.g. the auth/security page).
    docs_pages = raw_data.docs_pages or []
    per_page_budget = max(MAX_DOCS_CONTENT_CHARS // max(len(docs_pages), 1), 500)

    docs_content = ""
    for page in docs_pages:
        url = page.get("url", "unknown")
        content = truncate_text(page.get("content", ""), per_page_budget)
        docs_content += f"\n--- Source: {url} ---\n{content}\n"

    # If no docs content, note it
    if not docs_content.strip() or len(docs_content.strip()) < 50:
        docs_content = (
            "No documentation was found for this app. "
            "The agent could not locate developer docs, API references, or authentication guides. "
            "Please classify based on this absence of information."
        )

    # Format MCP check
    mcp_check = json.dumps(raw_data.mcp_check, indent=2) if raw_data.mcp_check else "No MCP check performed"

    # Format the classification prompt
    prompt = CLASSIFICATION_PROMPT.format(
        app_name=app_name,
        website=website,
        category=category,
        docs_content=docs_content,
        mcp_check=mcp_check,
    )

    # Call the LLM, transparently failing over to the next configured
    # provider if the primary one is rate-limited/quota-exhausted.
    try:
        response, provider_used = chat_completion_with_failover(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=CLASSIFICATION_MAX_TOKENS,
            temperature=TEMPERATURE,
            stage="classification",
        )

        # An empty `choices` list (safety filter, upstream glitch) is treated
        # the same as unparsable text below rather than raised immediately —
        # that way it gets the same stricter-prompt retry as invalid JSON
        # instead of failing the app outright on a single bad response.
        raw_text = response.choices[0].message.content or "" if response and response.choices else ""

        # Parse JSON response
        parsed = extract_json_from_text(raw_text)
        if parsed is not None:
            parsed = _normalize_taxonomy(parsed)

        if parsed is None or _taxonomy_errors(parsed):
            # Retry with stricter prompt
            issue = "invalid JSON" if parsed is None else "; ".join(_taxonomy_errors(parsed))
            logger.warning(f"  ⚠️  Invalid classification for {app_name} ({issue}), retrying...")
            retry_prompt = CLASSIFICATION_RETRY_PROMPT.format(
                app_name=app_name,
                website=website,
                docs_content=truncate_text(docs_content, 3000),
            )
            retry_response, provider_used = chat_completion_with_failover(
                messages=[{"role": "user", "content": retry_prompt}],
                max_tokens=CLASSIFICATION_MAX_TOKENS,
                temperature=TEMPERATURE,
                stage="classification",
            )

            raw_text = (
                retry_response.choices[0].message.content or ""
                if retry_response and retry_response.choices
                else ""
            )
            parsed = extract_json_from_text(raw_text)
            if parsed is not None:
                parsed = _normalize_taxonomy(parsed)

        if parsed is None or _taxonomy_errors(parsed):
            error = {
                "app": app_name,
                "error": "Invalid JSON or taxonomy after retry",
                "validation_errors": _taxonomy_errors(parsed) if parsed else ["invalid JSON"],
                "raw": raw_text,
            }
            logger.error(f"  ❌ {app_name}: invalid JSON/taxonomy after retry")
            return None, error

        # Build AppResearchResult
        result = AppResearchResult(
            id=app.id,
            name=app_name,
            website=website,
            category=category,
            one_liner=parsed.get("one_liner", ""),
            auth_methods=_ensure_list(parsed.get("auth_methods", [])),
            auth_primary=parsed.get("auth_primary", ""),
            auth_notes=parsed.get("auth_notes"),
            self_serve=_parse_bool(parsed.get("self_serve", False)),
            access_tier=parsed.get("access_tier", ""),
            access_notes=parsed.get("access_notes"),
            api_type=_ensure_list(parsed.get("api_type", [])),
            api_breadth=parsed.get("api_breadth", ""),
            api_docs_quality=parsed.get("api_docs_quality", ""),
            has_sdk=_parse_bool(parsed.get("has_sdk", False)),
            sdk_languages=_ensure_list(parsed.get("sdk_languages", [])),
            has_webhooks=_parse_bool(parsed.get("has_webhooks", False)),
            has_rate_limits=_parse_bool(parsed.get("has_rate_limits", False)),
            rate_limit_detail=parsed.get("rate_limit_detail"),
            has_existing_mcp=_parse_bool(parsed.get("has_existing_mcp", False)),
            mcp_source=parsed.get("mcp_source"),
            buildability=parsed.get("buildability", ""),
            buildability_rationale=parsed.get("buildability_rationale", ""),
            main_blocker=parsed.get("main_blocker"),
            evidence_urls=_ensure_list(parsed.get("evidence_urls", [])),
            confidence=parsed.get("confidence", "medium"),
            research_method=raw_data.research_method,
            researched_at=now_iso(),
            verified=False,
        )

        logger.info(
            f"  ✓ {app_name} [{provider_used}]: buildability={result.buildability}, "
            f"auth={result.auth_primary}, confidence={result.confidence}"
        )
        return result, None

    except Exception as e:
        if "rate_limit" in str(e).lower() or "timeout" in str(e).lower() or "connection" in str(e).lower():
            error = {"app": app_name, "error": f"API error: {e}", "type": "api_error"}
            logger.error(f"  ❌ {app_name}: all configured LLM providers failed — {e}")
            return None, error
        else:
            error = {"app": app_name, "error": str(e), "type": "unknown"}
            logger.error(f"  ❌ {app_name}: Unexpected error — {e}")
            return None, error


# ─── BATCH CLASSIFICATION PIPELINE ──────────────────────────────────────────


async def run_classification_pipeline(
    apps: List[AppInput],
    raw_data_list: List[RawResearchData],
    save_path: Optional[str] = None,
) -> Tuple[List[AppResearchResult], List[Dict]]:
    """
    Process all apps through LLM classification with progress tracking.
    Returns (results, failures).
    """
    save_path = save_path or str(CLASSIFIED_DIR / "results_v1.json")
    save_path_obj = Path(save_path)
    if "results" in save_path_obj.name:
        failures_path = save_path_obj.parent / save_path_obj.name.replace("results", "failures")
    else:
        failures_path = save_path_obj.parent / f"{save_path_obj.stem}_failures.json"

    provider_names = " -> ".join(f"{cfg['provider']} ({cfg['model']})" for cfg in LLM_PROVIDER_CHAIN)
    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 2: LLM CLASSIFICATION — {len(apps)} apps")
    logger.info(f"Provider chain: {provider_names or 'NONE CONFIGURED'}, Temperature: {TEMPERATURE}")
    logger.info(f"{'='*60}\n")

    if not LLM_PROVIDER_CHAIN:
        logger.error("No LLM provider API key configured! Cannot run classification.")
        return [], [{"error": "No API key"}]

    # Build lookup from app name to raw data
    raw_lookup = {rd.app_name: rd for rd in raw_data_list}

    results: List[AppResearchResult] = []
    failures: List[Dict] = []

    # Process in batches
    for batch_start in range(0, len(apps), CLASSIFICATION_BATCH_SIZE):
        batch = apps[batch_start : batch_start + CLASSIFICATION_BATCH_SIZE]

        # Process batch (sequentially within batch to respect rate limits)
        for app in batch:
            raw = raw_lookup.get(app.name)
            if not raw:
                # Create empty raw data if missing
                raw = RawResearchData(
                    app_name=app.name,
                    website=app.website,
                    research_method="no_research_data",
                    research_timestamp=now_iso(),
                )

            result, error = await classify_single_app(app, raw)

            if result:
                results.append(result)
            elif error:
                failures.append(error)

            # Small delay between individual calls
            await asyncio.sleep(0.5)

        # Progress
        done = min(batch_start + CLASSIFICATION_BATCH_SIZE, len(apps))
        logger.info(f"\n📊 Progress: {done}/{len(apps)} apps classified\n")

        # Checkpoint save
        if done % CHECKPOINT_EVERY_N == 0 or done == len(apps):
            save_json(
                [r.model_dump() for r in results],
                save_path,
            )
            if failures:
                save_json(failures, str(failures_path))
            logger.info(f"💾 Checkpoint saved: {save_path}")

        # Rate limit pause between batches
        if done < len(apps):
            await asyncio.sleep(CLASSIFICATION_BATCH_DELAY)

    # Final save
    save_json([r.model_dump() for r in results], save_path)
    if failures:
        save_json(failures, str(CLASSIFIED_DIR / "failures_v1.json"))

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 2 COMPLETE")
    logger.info(f"  ✅ Classified:   {len(results)}/{len(apps)}")
    logger.info(f"  ❌ Failed:       {len(failures)}/{len(apps)}")
    if results:
        easy = sum(1 for r in results if r.buildability == "easy")
        moderate = sum(1 for r in results if r.buildability == "moderate")
        hard = sum(1 for r in results if r.buildability == "hard")
        not_feasible = sum(1 for r in results if r.buildability == "not_feasible")
        logger.info(f"  🟢 Easy:         {easy}")
        logger.info(f"  🟡 Moderate:     {moderate}")
        logger.info(f"  🟠 Hard:         {hard}")
        logger.info(f"  🔴 Not feasible: {not_feasible}")
    logger.info(f"  💾 Saved to:     {save_path}")
    logger.info(f"{'='*60}\n")

    return results, failures


# ─── HELPERS ─────────────────────────────────────────────────────────────────


def _ensure_list(value: Any) -> List[str]:
    """Ensure a value is a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value if v and str(v).lower() != "null"]
    if isinstance(value, str):
        return [value] if value and value.lower() != "null" else []
    return []


def _parse_bool(value: Any) -> bool:
    """Parse a value to boolean, handling string representations."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1")
    return bool(value)


_TAXONOMY_ALLOWED: Dict[str, set] = {
    "auth_methods": {"OAuth2", "API_Key", "Basic", "Bearer_Token", "JWT", "HMAC", "Other", "None", "not_found"},
    "access_tier": {"free_tier", "free_trial", "paid_required", "contact_sales", "partner_gated", "open_source", "not_found"},
    "api_type": {"REST", "GraphQL", "SOAP", "WebSocket", "gRPC", "CLI_Only", "None", "not_found"},
    "api_breadth": {"narrow", "moderate", "broad", "not_found"},
    "api_docs_quality": {"excellent", "good", "minimal", "none", "not_found"},
    "buildability": {"easy", "moderate", "hard", "not_feasible", "not_found"},
    "confidence": {"high", "medium", "low", "not_found"},
}

# Synonym/near-miss values seen from weaker fallback models (e.g. OpenRouter's
# free tier, which doesn't reliably honor strict JSON-schema enums the way
# Groq's gpt-oss models do) mapped to their canonical taxonomy value. Keyed
# by the value lowercased with spaces/hyphens/underscores stripped.
_TAXONOMY_ALIASES: Dict[str, Dict[str, str]] = {
    "auth_methods": {
        "apikey": "API_Key", "key": "API_Key",
        "oauth": "OAuth2", "oauth20": "OAuth2",
        "basicauth": "Basic",
        "bearer": "Bearer_Token", "bearertoken": "Bearer_Token", "token": "Bearer_Token",
        "noauth": "None",
    },
    "access_tier": {
        "public": "free_tier", "free": "free_tier",
        "trial": "free_trial", "freetrial": "free_trial",
        "paid": "paid_required", "paidonly": "paid_required", "standard": "paid_required",
        "enterprise": "contact_sales", "contactsales": "contact_sales", "sales": "contact_sales",
        "gated": "partner_gated", "partner": "partner_gated",
        "opensource": "open_source",
    },
    "api_type": {
        "rest": "REST", "restful": "REST",
        "websocket": "WebSocket", "websockets": "WebSocket",
        "cli": "CLI_Only", "clionly": "CLI_Only",
    },
    "api_breadth": {"wide": "broad", "large": "broad", "extensive": "broad", "full": "broad", "small": "narrow", "limited": "narrow"},
    "api_docs_quality": {"high": "excellent", "great": "excellent", "low": "minimal", "poor": "minimal"},
    "buildability": {"high": "easy", "low": "hard", "possible": "moderate", "impossible": "not_feasible", "infeasible": "not_feasible"},
}

# auth_methods/auth_primary in particular tend to come back as a compound
# descriptor rather than a bare enum value ("OAuth2 Authorization Code",
# "Personal Access Token") — matched by substring against the stripped key
# since an exact/alias lookup would miss these. Ordered specific-to-generic
# so e.g. "OAuth2 ... Token" resolves to OAuth2, not the generic token bucket.
_AUTH_METHOD_KEYWORD_FALLBACK = (
    ("oauth", "OAuth2"),
    ("apikey", "API_Key"),
    ("bearer", "Bearer_Token"),
    ("jwt", "JWT"),
    ("hmac", "HMAC"),
    ("basic", "Basic"),
    ("token", "Bearer_Token"),
    ("key", "API_Key"),
)


def _coerce_taxonomy_value(field: str, value: Any) -> Any:
    """Map a synonym/differently-cased value onto the canonical taxonomy
    entry for `field`, leaving it unchanged if no match is found (so genuine
    garbage still fails validation and triggers a retry, rather than being
    silently accepted)."""
    if field == "confidence" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return "high" if value >= 0.8 else "medium" if value >= 0.5 else "low"
    if not isinstance(value, str):
        return value
    allowed = _TAXONOMY_ALLOWED.get(field)
    if allowed is None or value in allowed:
        return value
    key = value.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    for canonical in allowed:
        if canonical.lower().replace("_", "") == key:
            return canonical
    alias = _TAXONOMY_ALIASES.get(field, {}).get(key)
    if alias:
        return alias
    if field == "auth_methods":
        for needle, canonical in _AUTH_METHOD_KEYWORD_FALLBACK:
            if needle in key:
                return canonical
    return value


def _normalize_taxonomy(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce near-miss taxonomy values (wrong case, common synonyms) in
    place before validating, so a weaker fallback model's semantically
    correct but non-literal answer isn't rejected outright."""
    if not isinstance(parsed, dict):
        return parsed
    for field in _TAXONOMY_ALLOWED:
        if field not in parsed:
            continue
        value = parsed[field]
        if isinstance(value, list):
            parsed[field] = [_coerce_taxonomy_value(field, v) for v in value]
        else:
            parsed[field] = _coerce_taxonomy_value(field, value)
    if "auth_primary" in parsed:
        parsed["auth_primary"] = _coerce_taxonomy_value("auth_methods", parsed["auth_primary"])
    return parsed


def _taxonomy_errors(parsed: Dict[str, Any]) -> List[str]:
    """Reject plausible-looking output that cannot be compared across 100 apps."""
    errors = []
    for field, values in _TAXONOMY_ALLOWED.items():
        value = parsed.get(field)
        values_to_check = value if isinstance(value, list) else [value]
        for item in values_to_check:
            if item not in values:
                errors.append(f"{field}={item!r}")
    primary = parsed.get("auth_primary")
    if primary not in _TAXONOMY_ALLOWED["auth_methods"]:
        errors.append(f"auth_primary={primary!r}")
    return errors
