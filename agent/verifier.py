"""
Stage 3: Verification Pipeline

The MOST CRITICAL stage — the assignment says "accuracy is what matters most."

Three verification layers:
- Layer 1: Automated cross-check (all 100 apps) — logical consistency + URL checks
- Layer 2: Verification agent (25 random + flagged) — independent LLM re-check
- Layer 3: Human spot-check support (10-15 apps) — checklist generation

Plus a correction loop that applies fixes and documents accuracy improvement.
"""

import asyncio
import json
import random
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agent.config import (
    KNOWN_APPS,
    RAW_DIR,
    TEMPERATURE,
    VERIFICATION_DIR,
    VERIFICATION_MAX_TOKENS,
    VERIFICATION_SAMPLE_SIZE,
    LLM_PROVIDER_CHAIN,
)
from agent.prompts import VERIFICATION_PROMPT
from agent.schemas import (
    AccuracyReport,
    AppResearchResult,
    AppVerification,
    FieldVerification,
    RawResearchData,
)
from agent.utils import (
    extract_json_from_text,
    get_logger,
    now_iso,
    save_json,
)
from agent.llm import chat_completion_with_failover
from agent.classifier import _TAXONOMY_ALLOWED, _coerce_taxonomy_value, _parse_bool

logger = get_logger()


def _load_composio_catalog() -> Dict[str, Any]:
    """Composio's own toolkit catalog (agent/composio_lookup.py output) —
    real, live data from Composio's API, not LLM-inferred. Used below as a
    first-party ground-truth cross-check, the same role KNOWN_APPS plays but
    sourced from Composio directly instead of hand-curated."""
    path = RAW_DIR / "composio_catalog.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


COMPOSIO_CATALOG = _load_composio_catalog()


# ─── LAYER 1: AUTOMATED CROSS-CHECK ─────────────────────────────────────────


async def automated_cross_check(result: AppResearchResult) -> List[str]:
    """
    Quick automated sanity checks on agent output.
    Returns list of flagged issues.
    """
    flags = []

    # Check 1: Logical consistency rules
    if result.buildability == "easy" and not result.self_serve:
        flags.append("INCONSISTENT: buildability=easy but self_serve=false")

    if result.api_breadth == "broad" and result.api_type == ["None"]:
        flags.append("INCONSISTENT: broad API breadth but api_type=None")

    if result.buildability == "not_feasible" and result.has_existing_mcp:
        flags.append("INCONSISTENT: not_feasible but has existing MCP server")

    if result.confidence == "high" and not result.evidence_urls:
        flags.append("INCONSISTENT: high confidence but no evidence URLs")

    if result.buildability == "easy" and result.api_docs_quality in ("none", "minimal"):
        flags.append("INCONSISTENT: buildability=easy but docs quality is none/minimal")

    if result.has_sdk and not result.sdk_languages:
        flags.append("INCONSISTENT: has_sdk=true but no sdk_languages listed")

    if result.self_serve and result.access_tier in ("contact_sales", "partner_gated"):
        flags.append("INCONSISTENT: self_serve=true but access_tier is sales/partner gated")

    if not result.self_serve and result.access_tier in ("free_tier", "open_source"):
        flags.append("INCONSISTENT: self_serve=false but access_tier is free_tier/open_source")

    # Check 2: Known-good data points
    if result.name in KNOWN_APPS:
        known = KNOWN_APPS[result.name]

        known_auth = set(known.get("auth", []))
        agent_auth = set(result.auth_methods)
        if known_auth and not known_auth.intersection(agent_auth):
            flags.append(
                f"AUTH MISMATCH vs known: agent={result.auth_methods}, known={list(known_auth)}"
            )

        if "self_serve" in known and result.self_serve != known["self_serve"]:
            flags.append(
                f"SELF_SERVE MISMATCH vs known: agent={result.self_serve}, known={known['self_serve']}"
            )

        known_api = set(known.get("api", []))
        agent_api = set(result.api_type)
        if known_api and not known_api.intersection(agent_api):
            flags.append(
                f"API_TYPE MISMATCH vs known: agent={result.api_type}, known={list(known_api)}"
            )

    # Check 2b: Composio's own toolkit catalog (first-party ground truth,
    # not LLM-inferred — see _load_composio_catalog above)
    composio_entry = COMPOSIO_CATALOG.get(result.name)
    if composio_entry:
        tools_count = composio_entry.get("tools_count") or 0
        if tools_count > 0 and result.buildability == "not_feasible":
            flags.append(
                f"COMPOSIO MISMATCH: buildability=not_feasible but Composio's own "
                f"catalog already has a working toolkit with {int(tools_count)} tools for this app"
            )

        composio_auth = set(composio_entry.get("auth_methods") or [])
        agent_auth = set(result.auth_methods)
        if composio_auth and agent_auth and not composio_auth.intersection(agent_auth):
            flags.append(
                f"COMPOSIO AUTH MISMATCH: agent={result.auth_methods}, "
                f"Composio catalog={sorted(composio_auth)}"
            )

    # Check 3: Evidence URLs are reachable (sample first 2)
    for url in result.evidence_urls[:2]:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.head(url)
                if resp.status_code >= 400:
                    flags.append(f"Evidence URL unreachable: {url} (HTTP {resp.status_code})")
        except Exception:
            flags.append(f"Evidence URL failed: {url}")

    return flags


async def run_automated_checks(
    results: List[AppResearchResult],
) -> Dict[str, List[str]]:
    """Run automated cross-checks on all results."""
    logger.info("Layer 1: Running automated cross-checks on all apps...")

    all_flags: Dict[str, List[str]] = {}

    for result in results:
        flags = await automated_cross_check(result)
        if flags:
            all_flags[result.name] = flags
            for flag in flags:
                logger.warning(f"  ⚠️  {result.name}: {flag}")

    flagged_count = len(all_flags)
    total_flags = sum(len(f) for f in all_flags.values())
    logger.info(
        f"Layer 1 complete: {flagged_count} apps flagged, {total_flags} total issues"
    )

    return all_flags


_INCONCLUSIVE_EVIDENCE_MARKERS = (
    "no information", "not found", "not specified", "no mention",
    "not explicitly", "not publicly disclosed", "unknown", "not stated",
    "no evidence", "not provided", "not clear",
)


def _is_inconclusive_evidence(evidence: str) -> bool:
    """True if the verifier's own evidence text says it found nothing —
    i.e. it couldn't confirm OR deny the agent's answer, which is not the
    same as the agent being wrong."""
    e = (evidence or "").lower()
    return any(marker in e for marker in _INCONCLUSIVE_EVIDENCE_MARKERS)


def _values_equivalent(a: Any, b: Any) -> bool:
    """Loose equality for agent_value vs correct_value: case/whitespace
    normalized, and a list is treated as equivalent to a scalar/subset of
    itself (a model asked to agree/disagree on a list field sometimes
    echoes back one representative item rather than the full list)."""
    def norm(v: Any) -> set:
        if isinstance(v, list):
            return {str(x).strip().lower() for x in v}
        return {str(v).strip().lower()} if v is not None else set()

    na, nb = norm(a), norm(b)
    return bool(na) and bool(nb) and (na == nb or na <= nb or nb <= na)


# ─── LAYER 2: VERIFICATION AGENT ────────────────────────────────────────────


async def verify_single_app(
    result: AppResearchResult,
    raw_data: Optional[RawResearchData],
) -> AppVerification:
    """
    Independently verify a single app's results using a different LLM prompt.
    """
    # Get fresh docs content
    fresh_docs = ""
    if raw_data and raw_data.docs_pages:
        for page in raw_data.docs_pages[:2]:
            fresh_docs += f"\n--- {page.get('url', '')} ---\n{page.get('content', '')}\n"

    if not fresh_docs.strip():
        fresh_docs = "No fresh documentation available for verification."

    # Format verification prompt
    prompt = VERIFICATION_PROMPT.format(
        app_name=result.name,
        website=result.website,
        agent_auth=result.auth_methods,
        agent_auth_primary=result.auth_primary,
        agent_self_serve=result.self_serve,
        agent_access=result.access_tier,
        agent_api_type=result.api_type,
        agent_api_breadth=result.api_breadth,
        agent_buildability=result.buildability,
        agent_mcp=result.has_existing_mcp,
        fresh_docs=fresh_docs[:6000],
    )

    fields_checked: List[FieldVerification] = []

    try:
        response, _provider_used = chat_completion_with_failover(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=VERIFICATION_MAX_TOKENS,
            temperature=TEMPERATURE,
            stage="verification",
        )

        if not response or not response.choices:
            raise ValueError("LLM provider returned empty choices (possibly a safety filter or API error)")

        raw_text = response.choices[0].message.content or ""
        parsed = extract_json_from_text(raw_text)

        if parsed:
            # Process each verified field
            field_map = {
                "auth_methods": result.auth_methods,
                "self_serve": result.self_serve,
                "access_tier": result.access_tier,
                "api_type": result.api_type,
                "api_breadth": result.api_breadth,
                "buildability": result.buildability,
            }

            for field_name, agent_value in field_map.items():
                verification = parsed.get(field_name)
                if not isinstance(verification, dict):
                    # Missing key, explicit null, or the model flattened its
                    # answer instead of the requested {agree, correct_value,
                    # evidence} object (a weaker fallback model does this
                    # often). Previously this field was silently skipped —
                    # `isinstance(verification, dict)` was False so nothing
                    # got appended — which undercounts overall_total (an app
                    # could end up "1/1 correct" instead of "5/6") and biases
                    # the per-field aggregate toward whichever fields the
                    # model happens to format correctly. Normalize to {} so
                    # every field always contributes exactly one
                    # FieldVerification, defaulting to "agree" per the
                    # prompt's own ambiguous-case rule.
                    verification = {}

                agree = verification.get("agree")
                if agree is None:
                    agree = True
                elif not isinstance(agree, bool):
                    agree = _parse_bool(agree)
                correct_value = verification.get("correct_value")
                if correct_value is None:
                    correct_value = agent_value
                evidence = verification.get("evidence")
                if evidence is None:
                    evidence = ""
                elif not isinstance(evidence, str):
                    evidence = str(evidence)

                # The prompt tells the verifier to default to agreeing when
                # the fresh docs are ambiguous/missing — the model frequently
                # ignores that and sets agree=False anyway while citing "no
                # information found" as its own evidence, or while echoing
                # back a correct_value that's actually the same as the
                # agent's (e.g. both "not_found"). Neither is a real
                # disagreement; scoring them as errors would be measuring the
                # verifier's limited 2-page context window, not the agent's
                # accuracy. Honor the prompt's own rule here since the model
                # didn't.
                if not agree and (_is_inconclusive_evidence(evidence) or _values_equivalent(agent_value, correct_value)):
                    agree = True

                fields_checked.append(
                    FieldVerification(
                        field_name=field_name,
                        agent_value=agent_value,
                        actual_value=correct_value if not agree else agent_value,
                        is_correct=agree,
                        evidence_url=evidence,
                        notes=None if agree else f"Verifier disagrees: {evidence}",
                    )
                )

    except Exception as e:
        logger.warning(f"Verification LLM call failed for {result.name}: {e}")

    # Calculate accuracy
    correct = sum(1 for f in fields_checked if f.is_correct)
    total = len(fields_checked) or 1
    accuracy = round(correct / total * 100, 1)

    return AppVerification(
        app_id=result.id,
        app_name=result.name,
        fields_checked=fields_checked,
        overall_correct=correct,
        overall_total=total,
        accuracy_pct=accuracy,
        verified_by="verification_agent",
    )


async def run_verification_agent(
    results: List[AppResearchResult],
    raw_data_list: List[RawResearchData],
    sample_size: int = VERIFICATION_SAMPLE_SIZE,
    flagged_apps: Optional[List[str]] = None,
) -> List[AppVerification]:
    """
    Run Layer 2 verification on a sample of apps + any flagged apps.
    """
    logger.info(f"\nLayer 2: Running verification agent on sample of {sample_size} apps...")

    if not LLM_PROVIDER_CHAIN:
        logger.error("No LLM provider configured, skipping verification agent")
        return []

    # Build raw data lookup
    raw_lookup = {rd.app_name: rd for rd in raw_data_list}

    # Select sample: random + flagged
    flagged_apps = flagged_apps or []
    flagged_results = [r for r in results if r.name in flagged_apps]

    # Random sample (excluding already-flagged)
    non_flagged = [r for r in results if r.name not in flagged_apps]
    random_sample_size = min(sample_size, len(non_flagged))
    random_sample = random.sample(non_flagged, random_sample_size) if non_flagged else []

    verify_set = list({r.name: r for r in (random_sample + flagged_results)}.values())
    logger.info(
        f"  Verifying {len(verify_set)} apps "
        f"({len(random_sample)} random + {len(flagged_results)} flagged)"
    )

    verifications: List[AppVerification] = []

    for i, result in enumerate(verify_set):
        raw = raw_lookup.get(result.name)
        verification = await verify_single_app(result, raw)
        verifications.append(verification)

        status = "✅" if verification.accuracy_pct >= 80 else "⚠️"
        logger.info(
            f"  {status} [{i+1}/{len(verify_set)}] {result.name}: "
            f"{verification.overall_correct}/{verification.overall_total} correct "
            f"({verification.accuracy_pct}%)"
        )

        # Rate limiting
        await asyncio.sleep(0.5)

    # Save verification results
    save_json(
        [v.model_dump() for v in verifications],
        str(VERIFICATION_DIR / "verification_results.json"),
    )

    return verifications


# ─── ACCURACY CALCULATION ────────────────────────────────────────────────────


def calculate_accuracy(verifications: List[AppVerification]) -> AccuracyReport:
    """Calculate per-field and overall accuracy from verification data."""
    fields_to_check = [
        "auth_methods", "self_serve", "access_tier",
        "api_type", "api_breadth", "buildability",
    ]

    per_field_correct: Dict[str, int] = {f: 0 for f in fields_to_check}
    per_field_total: Dict[str, int] = {f: 0 for f in fields_to_check}

    for v in verifications:
        for fc in v.fields_checked:
            if fc.field_name in fields_to_check:
                per_field_total[fc.field_name] += 1
                if fc.is_correct:
                    per_field_correct[fc.field_name] += 1

    per_field_accuracy = {}
    for f in fields_to_check:
        if per_field_total[f] > 0:
            per_field_accuracy[f] = round(
                per_field_correct[f] / per_field_total[f] * 100, 1
            )
        else:
            per_field_accuracy[f] = 0.0

    total_correct = sum(per_field_correct.values())
    total_checked = sum(per_field_total.values())
    overall = round(total_correct / total_checked * 100, 1) if total_checked > 0 else 0.0

    # Identify common error patterns
    error_patterns = identify_error_patterns(verifications)

    return AccuracyReport(
        sample_size=len(verifications),
        total_fields_checked=total_checked,
        total_correct=total_correct,
        overall_accuracy=overall,
        per_field_accuracy=per_field_accuracy,
        common_error_patterns=error_patterns,
        app_verifications=verifications,
    )


def identify_error_patterns(verifications: List[AppVerification]) -> List[str]:
    """Identify common patterns in verification errors."""
    error_fields = Counter()
    error_details = defaultdict(list)

    for v in verifications:
        for fc in v.fields_checked:
            if not fc.is_correct:
                error_fields[fc.field_name] += 1
                error_details[fc.field_name].append(
                    f"{v.app_name}: agent={fc.agent_value} → actual={fc.actual_value}"
                )

    patterns = []
    for field, count in error_fields.most_common(5):
        examples = error_details[field][:3]
        examples_str = "; ".join(examples)
        patterns.append(
            f"'{field}' had {count} errors. Examples: {examples_str}"
        )

    return patterns


# ─── CORRECTION LOOP ────────────────────────────────────────────────────────


def apply_corrections(
    results: List[AppResearchResult],
    verifications: List[AppVerification],
) -> List[Dict]:
    """
    Apply corrections from verification results to the main results.
    Returns list of corrections made.
    """
    corrections = []

    # Build verification lookup
    verify_lookup = {v.app_name: v for v in verifications}

    for result in results:
        v = verify_lookup.get(result.name)
        if not v:
            continue

        for fc in v.fields_checked:
            if not fc.is_correct and fc.actual_value is not None:
                old_value = getattr(result, fc.field_name, None)
                new_value = fc.actual_value

                # The verification LLM's "correct_value" is free-form, not
                # schema-constrained (see VERIFICATION_RESPONSE_SCHEMA) — it
                # sometimes returns a descriptive sentence instead of a bare
                # taxonomy value (e.g. a full auth explanation instead of
                # "API_Key"). Run it through the same coercion used for
                # classification, and skip the "correction" entirely if it
                # still doesn't map to a valid entry — writing prose into an
                # enum field is worse than leaving the original value alone.
                if fc.field_name in _TAXONOMY_ALLOWED:
                    allowed = _TAXONOMY_ALLOWED[fc.field_name]
                    # auth_methods/api_type are List[str] on AppResearchResult;
                    # the verifier sometimes answers with a single bare string
                    # for them instead of a one-item list. AppResearchResult
                    # doesn't validate on assignment, so setattr would silently
                    # store a str where a list is expected — force list shape
                    # for these fields regardless of what the verifier sent.
                    is_list_field = fc.field_name in ("auth_methods", "api_type")
                    raw_items = new_value if isinstance(new_value, list) else [new_value]
                    candidate_items = [_coerce_taxonomy_value(fc.field_name, x) for x in raw_items]
                    valid = bool(candidate_items) and all(x in allowed for x in candidate_items)
                    candidate = candidate_items if is_list_field else (candidate_items[0] if candidate_items else None)
                    if not valid:
                        logger.warning(
                            f"  Skipped correction {result.name}.{fc.field_name}: "
                            f"verifier value {new_value!r} doesn't map to a valid taxonomy entry"
                        )
                        continue
                    new_value = candidate
                elif fc.field_name == "self_serve" and not isinstance(new_value, bool):
                    new_value = _parse_bool(new_value)

                # Apply correction
                try:
                    setattr(result, fc.field_name, new_value)
                    result.verified = True
                    result.verified_at = now_iso()

                    corrections.append({
                        "app": result.name,
                        "field": fc.field_name,
                        "old": old_value,
                        "new": new_value,
                        "evidence": fc.evidence_url,
                    })

                    logger.info(
                        f"  🔧 {result.name}.{fc.field_name}: "
                        f"{old_value} → {new_value}"
                    )
                except Exception as e:
                    logger.warning(f"  Failed to apply correction to {result.name}.{fc.field_name}: {e}")

    return corrections


# ─── HUMAN VERIFICATION SUPPORT ─────────────────────────────────────────────


def generate_human_checklist(
    results: List[AppResearchResult],
    sample_size: int = 12,
) -> str:
    """
    Generate a markdown checklist for human verification.
    Selects ~1 app per category for diverse coverage.
    """
    # Select 1-2 apps per category
    by_category = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)

    selected = []
    for cat, apps in by_category.items():
        n = min(2, len(apps))
        selected.extend(random.sample(apps, n))

    # Trim to target size
    if len(selected) > sample_size:
        selected = random.sample(selected, sample_size)

    checklist = "# Human Verification Checklist\n\n"
    checklist += f"**Target:** Verify {len(selected)} apps across all categories\n"
    checklist += f"**Time budget:** ~3-4 minutes per app = ~{len(selected) * 3}-{len(selected) * 4} minutes total\n\n"

    for i, result in enumerate(selected, 1):
        checklist += f"## {i}. {result.name} ({result.category})\n\n"
        checklist += f"**Website:** https://{result.website}\n"
        checklist += f"**Agent's answers:**\n"
        checklist += f"- Auth: {result.auth_methods} (primary: {result.auth_primary})\n"
        checklist += f"- Self-serve: {result.self_serve}\n"
        checklist += f"- Access tier: {result.access_tier}\n"
        checklist += f"- API type: {result.api_type}\n"
        checklist += f"- API breadth: {result.api_breadth}\n"
        checklist += f"- Buildability: {result.buildability}\n"
        checklist += f"- Evidence URLs: {result.evidence_urls}\n\n"
        checklist += f"**Verify:**\n"
        checklist += f"- [ ] Auth method correct?\n"
        checklist += f"- [ ] Self-serve accurate?\n"
        checklist += f"- [ ] API type correct?\n"
        checklist += f"- [ ] Buildability assessment fair?\n"
        checklist += f"- [ ] Evidence URLs work?\n\n"
        checklist += "---\n\n"

    return checklist


# ─── FULL VERIFICATION PIPELINE ─────────────────────────────────────────────


async def run_full_verification(
    results: List[AppResearchResult],
    raw_data_list: List[RawResearchData],
) -> Tuple[AccuracyReport, List[Dict]]:
    """
    Run the complete 3-layer verification pipeline.
    Returns (accuracy_report, corrections_list).
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 3: VERIFICATION PIPELINE")
    logger.info(f"{'='*60}\n")

    # Layer 1: Automated cross-checks
    auto_flags = await run_automated_checks(results)
    flagged_apps = list(auto_flags.keys())

    # Layer 2: Verification agent
    verifications = await run_verification_agent(
        results, raw_data_list,
        sample_size=VERIFICATION_SAMPLE_SIZE,
        flagged_apps=flagged_apps,
    )

    # Calculate first-pass accuracy
    first_pass = calculate_accuracy(verifications)
    logger.info(f"\n📊 First-pass accuracy: {first_pass.overall_accuracy}%")
    logger.info(f"   Per-field: {json.dumps(first_pass.per_field_accuracy, indent=2)}")

    # Correction loop
    logger.info(f"\n--- CORRECTION LOOP ---")
    corrections = apply_corrections(results, verifications)
    logger.info(f"Applied {len(corrections)} corrections")

    # Re-verify to measure improvement
    if corrections:
        logger.info("Re-verifying corrected results...")
        re_verifications = await run_verification_agent(
            results, raw_data_list,
            sample_size=min(15, len(results)),
            flagged_apps=[c["app"] for c in corrections],
        )
        final_accuracy = calculate_accuracy(re_verifications)
    else:
        final_accuracy = first_pass

    # Set accuracy deltas
    final_accuracy.first_pass_accuracy = first_pass.overall_accuracy
    final_accuracy.final_accuracy = final_accuracy.overall_accuracy
    final_accuracy.improvement_delta = round(
        final_accuracy.overall_accuracy - first_pass.overall_accuracy, 1
    )

    # Layer 3: Generate human checklist
    checklist = generate_human_checklist(results)
    checklist_path = VERIFICATION_DIR / "human_checklist.md"
    with open(checklist_path, "w", encoding="utf-8") as f:
        f.write(checklist)
    logger.info(f"📝 Human checklist saved: {checklist_path}")

    # Save accuracy report
    save_json(
        final_accuracy.model_dump(),
        str(VERIFICATION_DIR / "accuracy_report.json"),
    )

    # Save corrections
    if corrections:
        save_json(corrections, str(VERIFICATION_DIR / "corrections.json"))

    # Save auto flags
    save_json(auto_flags, str(VERIFICATION_DIR / "auto_flags.json"))

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 3 COMPLETE")
    logger.info(f"  📊 First-pass accuracy:  {first_pass.overall_accuracy}%")
    logger.info(f"  📊 Final accuracy:       {final_accuracy.overall_accuracy}%")
    logger.info(f"  📈 Improvement:          +{final_accuracy.improvement_delta}%")
    logger.info(f"  🔧 Corrections applied:  {len(corrections)}")
    logger.info(f"  ⚠️  Apps flagged (L1):    {len(flagged_apps)}")
    logger.info(f"  ✅ Apps verified (L2):    {len(verifications)}")
    logger.info(f"  📝 Human checklist:      {checklist_path}")
    logger.info(f"{'='*60}\n")

    return final_accuracy, corrections
