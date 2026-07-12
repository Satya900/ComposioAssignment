"""
Stage 4: Pattern Analysis Engine

Transforms 100 individual app results into cross-cutting insights.
This is where the "Product Ops" brain shows — not just data, but implications.

Analyzes 8 dimensions:
1. Auth distribution
2. Self-serve vs gated by category
3. Buildability scorecard
4. Common blockers
5. MCP landscape
6. Strategic quadrant (self-serve × API breadth)
7. Docs quality vs buildability correlation
8. Composio catalog coverage (already-built vs net-new opportunity)
"""

import json
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from agent.config import FINAL_DIR
from agent.schemas import AppResearchResult, PatternInsight, PatternReport
from agent.utils import get_logger, save_json

logger = get_logger()


def analyze_patterns(results: List[AppResearchResult]) -> PatternReport:
    """
    Run all pattern analyses and generate insights.
    Returns a PatternReport with 5-8 sharp, data-backed insights.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 4: PATTERN ANALYSIS — {len(results)} apps")
    logger.info(f"{'='*60}\n")

    insights: List[PatternInsight] = []

    # ─── DIMENSION 1: Auth Distribution ──────────────────────────────────

    auth_dist = Counter()
    auth_by_category = defaultdict(Counter)
    for r in results:
        primary = r.auth_primary or "Unknown"
        auth_dist[primary] += 1
        auth_by_category[r.category][primary] += 1

    if auth_dist:
        dominant_auth = auth_dist.most_common(1)[0]
        second_auth = auth_dist.most_common(2)[1] if len(auth_dist) > 1 else ("None", 0)

        # Find which categories use which auth
        oauth_cats = [cat for cat, counts in auth_by_category.items()
                      if counts.get("OAuth2", 0) > counts.get("API_Key", 0)]
        apikey_cats = [cat for cat, counts in auth_by_category.items()
                       if counts.get("API_Key", 0) >= counts.get("OAuth2", 0)
                       and counts.get("API_Key", 0) > 0]

        insights.append(PatternInsight(
            headline=(
                f"{dominant_auth[0]} dominates at {dominant_auth[1]}% "
                f"({dominant_auth[1]}/{len(results)} apps), "
                f"while {second_auth[0]} covers {second_auth[1]} apps — "
                f"Composio needs two integration fast-paths"
            ),
            category="auth",
            supporting_data={
                "distribution": dict(auth_dist),
                "oauth2_categories": oauth_cats[:5],
                "api_key_categories": apikey_cats[:5],
            },
            affected_apps=[r.name for r in results if r.auth_primary == dominant_auth[0]],
            implication=(
                f"OAuth2 dominates customer-facing categories ({', '.join(oauth_cats[:3])}) "
                f"while API keys are preferred in developer tools. "
                f"Composio should invest heavily in OAuth2 infrastructure but maintain "
                f"an API-key fast-path for quick-integration apps."
            ),
        ))

    # ─── DIMENSION 2: Self-Serve vs Gated by Category ────────────────────

    access_by_cat = defaultdict(lambda: {"self_serve": 0, "gated": 0, "apps": {"self_serve": [], "gated": []}})
    for r in results:
        key = "self_serve" if r.self_serve else "gated"
        access_by_cat[r.category][key] += 1
        access_by_cat[r.category]["apps"][key].append(r.name)

    if access_by_cat:
        most_open = max(access_by_cat.items(), key=lambda x: x[1]["self_serve"])
        most_gated = max(access_by_cat.items(), key=lambda x: x[1]["gated"])
        total_self_serve = sum(1 for r in results if r.self_serve)
        total_gated = len(results) - total_self_serve

        insights.append(PatternInsight(
            headline=(
                f"{total_self_serve}/{len(results)} apps are self-serve; "
                f"{most_open[0]} is the most open ({most_open[1]['self_serve']}/10), "
                f"{most_gated[0]} is the most gated ({most_gated[1]['gated']}/10)"
            ),
            category="access",
            supporting_data={
                "total_self_serve": total_self_serve,
                "total_gated": total_gated,
                "by_category": {k: {"self_serve": v["self_serve"], "gated": v["gated"]}
                                for k, v in access_by_cat.items()},
            },
            affected_apps=access_by_cat[most_gated[0]]["apps"]["gated"],
            implication=(
                f"Start with {most_open[0]} for fast toolkit coverage — "
                f"most apps are self-serve and ready today. "
                f"For {most_gated[0]}, plan a dedicated outreach/partnership strategy."
            ),
        ))

    # ─── DIMENSION 3: Buildability Scorecard ─────────────────────────────

    build_counts = Counter(r.buildability for r in results)
    build_by_cat = defaultdict(Counter)
    for r in results:
        build_by_cat[r.category][r.buildability] += 1

    easy_wins = [r.name for r in results if r.buildability == "easy"]
    moderate_apps = [r.name for r in results if r.buildability == "moderate"]
    hard_apps = [r.name for r in results if r.buildability == "hard"]
    not_feasible_apps = [r.name for r in results if r.buildability == "not_feasible"]
    needs_outreach = [r.name for r in results
                      if r.access_tier in ("contact_sales", "partner_gated")]

    insights.append(PatternInsight(
        headline=(
            f"{len(easy_wins)} apps are ready to build as agent toolkits TODAY; "
            f"{len(moderate_apps)} with minor friction; "
            f"{len(needs_outreach)} need outreach or partnerships"
        ),
        category="buildability",
        supporting_data={
            "easy": len(easy_wins),
            "moderate": len(moderate_apps),
            "hard": len(hard_apps),
            "not_feasible": len(not_feasible_apps),
            "needs_outreach": len(needs_outreach),
            "by_category": {k: dict(v) for k, v in build_by_cat.items()},
        },
        affected_apps=easy_wins,
        implication=(
            f"Prioritize the {len(easy_wins)} easy-win apps for immediate toolkit coverage. "
            f"This gives Composio a large catalog quickly while outreach handles the rest."
        ),
    ))

    # ─── DIMENSION 4: Common Blockers ────────────────────────────────────

    blocker_counts = Counter()
    blocker_apps = defaultdict(list)
    for r in results:
        if r.main_blocker and r.main_blocker.lower() not in ("null", "none", "not_found"):
            # Normalize blocker text
            blocker = _normalize_blocker(r.main_blocker)
            blocker_counts[blocker] += 1
            blocker_apps[blocker].append(r.name)

    if blocker_counts:
        top_blocker = blocker_counts.most_common(1)[0]
        insights.append(PatternInsight(
            headline=(
                f"Top blocker: '{top_blocker[0]}' affects {top_blocker[1]} apps — "
                f"not just auth complexity, but fundamental access barriers"
            ),
            category="blockers",
            supporting_data={
                "ranked_blockers": [
                    {"blocker": b, "count": c, "apps": blocker_apps[b][:5]}
                    for b, c in blocker_counts.most_common(10)
                ],
            },
            affected_apps=blocker_apps[top_blocker[0]][:10],
            implication=(
                f"Address '{top_blocker[0]}' systematically — it would unlock "
                f"{top_blocker[1]} apps at once. Consider building a partnership "
                f"program or specialized auth handlers for this blocker category."
            ),
        ))

    # ─── DIMENSION 5: MCP Landscape ──────────────────────────────────────

    has_mcp = [r for r in results if r.has_existing_mcp]
    mcp_ready = [r for r in results
                 if not r.has_existing_mcp
                 and r.buildability in ("easy", "moderate")
                 and r.self_serve]

    insights.append(PatternInsight(
        headline=(
            f"Only {len(has_mcp)}/{len(results)} apps have existing MCP servers — "
            f"{len(mcp_ready)} more are MCP-ready but unserved (massive whitespace)"
        ),
        category="mcp",
        supporting_data={
            "existing_mcp_count": len(has_mcp),
            "existing_mcp_apps": [r.name for r in has_mcp],
            "mcp_ready_count": len(mcp_ready),
            "mcp_ready_apps": [r.name for r in mcp_ready[:20]],
            "mcp_gap": len(mcp_ready),
        },
        affected_apps=[r.name for r in mcp_ready[:15]],
        implication=(
            f"Composio has a first-mover opportunity on {len(mcp_ready)} apps. "
            f"These apps have self-serve access + decent APIs but no MCP server yet. "
            f"Being the first MCP provider creates lock-in and community gravity."
        ),
    ))

    # ─── DIMENSION 6: Strategic 2×2 Quadrant ────────────────────────────

    quadrants: Dict[str, List[str]] = {
        "easy_wins": [],       # Self-serve + Broad/Moderate API
        "quick_builds": [],    # Self-serve + Narrow API
        "worth_outreach": [],  # Gated + Broad/Moderate API
        "deprioritize": [],    # Gated + Narrow API
    }

    for r in results:
        is_broad = r.api_breadth in ("moderate", "broad")
        if r.self_serve and is_broad:
            quadrants["easy_wins"].append(r.name)
        elif r.self_serve and not is_broad:
            quadrants["quick_builds"].append(r.name)
        elif not r.self_serve and is_broad:
            quadrants["worth_outreach"].append(r.name)
        else:
            quadrants["deprioritize"].append(r.name)

    insights.append(PatternInsight(
        headline=(
            f"Strategic quadrant: {len(quadrants['easy_wins'])} easy wins, "
            f"{len(quadrants['quick_builds'])} quick builds, "
            f"{len(quadrants['worth_outreach'])} worth outreach, "
            f"{len(quadrants['deprioritize'])} to deprioritize"
        ),
        category="strategy",
        supporting_data=quadrants,
        affected_apps=quadrants["easy_wins"],
        implication=(
            f"The self-serve × API-breadth matrix is the prioritization framework. "
            f"Ship the {len(quadrants['easy_wins'])} easy wins first, "
            f"then the {len(quadrants['quick_builds'])} quick builds for fast catalog growth, "
            f"then invest outreach in the {len(quadrants['worth_outreach'])} high-value gated apps."
        ),
    ))

    # ─── DIMENSION 7: Docs Quality vs Buildability Correlation ───────────

    docs_quality_dist = Counter(r.api_docs_quality for r in results)
    excellent_easy = sum(1 for r in results
                         if r.api_docs_quality == "excellent" and r.buildability == "easy")
    none_hard = sum(1 for r in results
                     if r.api_docs_quality in ("none", "minimal")
                     and r.buildability in ("hard", "not_feasible"))

    if docs_quality_dist:
        insights.append(PatternInsight(
            headline=(
                f"Docs quality predicts buildability: "
                f"{excellent_easy} apps with excellent docs are easy builds; "
                f"{none_hard} with no/minimal docs are hard/infeasible"
            ),
            category="strategy",
            supporting_data={
                "docs_distribution": dict(docs_quality_dist),
                "excellent_and_easy": excellent_easy,
                "no_docs_and_hard": none_hard,
            },
            affected_apps=[r.name for r in results
                          if r.api_docs_quality in ("none", "minimal")][:10],
            implication=(
                "Documentation quality is the strongest predictor of buildability. "
                "Composio could partner with apps that have strong APIs but weak docs "
                "to create better documentation — unlocking integration for both parties."
            ),
        ))

    # ─── DIMENSION 8: Composio Catalog Coverage ──────────────────────────
    # Ground truth from Composio's own toolkit catalog (agent/composio_lookup.py),
    # not LLM-inferred — this is the one dimension where "does Composio already
    # have this?" is answered directly by Composio's own API rather than by
    # scraped docs + classification.

    already_covered = [r for r in results if r.composio_toolkit_exists]
    net_new = [r for r in results if not r.composio_toolkit_exists]
    total_existing_tools = sum(r.composio_tools_count or 0 for r in already_covered)
    net_new_easy_wins = [r for r in net_new if r.buildability == "easy"]

    if results:
        insights.append(PatternInsight(
            headline=(
                f"{len(already_covered)}/{len(results)} researched apps already exist as Composio "
                f"toolkits ({total_existing_tools} tools total) — the real net-new opportunity is "
                f"the other {len(net_new)}, of which {len(net_new_easy_wins)} are easy wins today"
            ),
            category="mcp",
            supporting_data={
                "already_covered_count": len(already_covered),
                "already_covered_apps": [r.name for r in already_covered],
                "total_existing_tools": total_existing_tools,
                "net_new_count": len(net_new),
                "net_new_easy_win_apps": [r.name for r in net_new_easy_wins],
            },
            affected_apps=[r.name for r in net_new_easy_wins[:15]],
            implication=(
                f"Cross-checking against Composio's own catalog (not just LLM classification) "
                f"separates 'already built' from 'actually new' — of the {len(net_new)} apps with "
                f"no existing Composio toolkit, {len(net_new_easy_wins)} are self-serve with a "
                f"broad-enough API to ship immediately, making them the highest-leverage next builds."
            ),
        ))

    # ─── ACCESS TIER DISTRIBUTION ────────────────────────────────────────

    access_dist = Counter(r.access_tier for r in results)

    # ─── BUILD PATTERN REPORT ────────────────────────────────────────────

    report = PatternReport(
        insights=insights,
        auth_distribution=dict(auth_dist),
        access_distribution=dict(access_dist),
        buildability_by_category={k: dict(v) for k, v in build_by_cat.items()},
        mcp_coverage={
            "has_mcp": [r.name for r in has_mcp],
            "mcp_ready": [r.name for r in mcp_ready],
        },
        top_blockers=[
            {"blocker": b, "count": c} for b, c in blocker_counts.most_common(10)
        ],
        easy_wins=easy_wins,
        needs_outreach=needs_outreach,
    )

    # Save
    save_json(report.model_dump(), str(FINAL_DIR / "patterns.json"))

    # Log insights
    logger.info(f"\n📊 Generated {len(insights)} insights:")
    for i, insight in enumerate(insights, 1):
        logger.info(f"  {i}. {insight.headline}")

    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 4 COMPLETE — {len(insights)} insights generated")
    logger.info(f"{'='*60}\n")

    return report


def _normalize_blocker(blocker: str) -> str:
    """Normalize blocker text for consistent grouping."""
    blocker = blocker.lower().strip()

    # Common normalizations
    mappings = {
        "no public api": "No public API",
        "no api": "No public API",
        "no public api docs": "No public API docs",
        "sales-gated": "Sales/enterprise gated",
        "contact sales": "Sales/enterprise gated",
        "enterprise only": "Sales/enterprise gated",
        "partner gated": "Partner/partnership required",
        "partnership required": "Partner/partnership required",
        "paid required": "Paid plan required for API",
        "paid plan": "Paid plan required for API",
        "auth complexity": "Complex authentication",
        "complex auth": "Complex authentication",
        "oauth complexity": "Complex authentication",
        "rate limits": "Restrictive rate limits",
        "rate limiting": "Restrictive rate limits",
        "poor docs": "Poor/missing documentation",
        "minimal docs": "Poor/missing documentation",
        "no docs": "Poor/missing documentation",
        "cli only": "CLI-only (no web API)",
        "cli tool": "CLI-only (no web API)",
    }

    for key, value in mappings.items():
        if key in blocker:
            return value

    # Capitalize first letter
    return blocker.capitalize()
