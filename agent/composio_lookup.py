"""
Composio Toolkit Catalog Lookup

Uses the current, official `composio` SDK (not the deprecated `composio-core`
/ ComposioToolSet API that composio-app-research/agent/researcher.py used to
reference) to query Composio's own toolkit catalog for each of the 100 apps.

Where a match exists, this is first-party ground truth: the real auth
schemes Composio integrates with for that app, and how many tools/triggers
it already exposes. That is a much stronger, more honest "is this already
an agent toolkit" signal than anything inferred from scraped public docs,
and it directly answers the assignment's core buildability question for
any app already in Composio's catalog.
"""

import re
from typing import Any, Dict, List, Optional

from composio import Composio

from agent.config import COMPOSIO_API_KEY
from agent.schemas import AppInput
from agent.utils import get_logger, save_json

logger = get_logger()

# Composio's `mode` values on auth_config_details -> our AuthMethod enum
_AUTH_MODE_MAP = {
    "OAUTH2": "OAuth2",
    "OAUTH1": "OAuth2",
    "API_KEY": "API_Key",
    "BEARER_TOKEN": "Bearer_Token",
    "BASIC": "Basic",
    "BASIC_WITH_JWT": "JWT",
    "SERVICE_ACCOUNT": "Other",
    "NO_AUTH": "None",
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def get_client() -> Optional[Composio]:
    if not COMPOSIO_API_KEY:
        return None
    return Composio(api_key=COMPOSIO_API_KEY)


def _extract_toolkit_summary(d: Dict[str, Any]) -> Dict[str, Any]:
    meta = d.get("meta") or {}
    categories = meta.get("categories") or [{}]
    auth_modes = sorted(
        {
            _AUTH_MODE_MAP.get(a.get("mode"), a.get("mode"))
            for a in (d.get("auth_config_details") or [])
            if a.get("mode")
        }
    )
    return {
        "slug": d.get("slug"),
        "name": d.get("name"),
        "category": categories[0].get("slug"),
        "description": meta.get("description"),
        "tools_count": meta.get("tools_count"),
        "triggers_count": meta.get("triggers_count"),
        "auth_methods": auth_modes,
        "app_url": meta.get("app_url"),
    }


def lookup_toolkit(client: Composio, app_name: str) -> Optional[Dict[str, Any]]:
    """Direct slug guess first (cheap), then fall back to fuzzy catalog search."""
    slug_guess = _normalize(app_name)
    try:
        r = client.client.toolkits.retrieve(slug_guess)
        return _extract_toolkit_summary(r.model_dump() if hasattr(r, "model_dump") else r)
    except Exception:
        pass

    try:
        res = client.client.toolkits.list(search=app_name)
        rd = res.model_dump() if hasattr(res, "model_dump") else res
        target = _normalize(app_name)
        for item in rd.get("items", []):
            if _normalize(item.get("name", "")) == target or _normalize(item.get("slug", "")) == target:
                r = client.client.toolkits.retrieve(item["slug"])
                return _extract_toolkit_summary(r.model_dump() if hasattr(r, "model_dump") else r)
    except Exception as e:
        logger.warning(f"Composio catalog search failed for {app_name}: {e}")

    return None


def enrich_results_with_catalog(
    results: List[Any], catalog: Dict[str, Any]
) -> int:
    """
    Merge the Composio catalog lookup onto already-classified AppResearchResult
    objects in place, setting composio_toolkit_exists/composio_tools_count.
    This is a deterministic dict merge against Composio's own catalog data —
    no LLM call, no cost, and unlike every other field on the result it isn't
    inferred from scraped docs, so it's the one field that's ground truth by
    construction rather than by verification.
    Returns the number of results that had a catalog match.
    """
    matched = 0
    for r in results:
        entry = catalog.get(r.name)
        if entry:
            r.composio_toolkit_exists = True
            r.composio_tools_count = entry.get("tools_count")
            matched += 1
        else:
            r.composio_toolkit_exists = False
            r.composio_tools_count = None
    return matched


def run_composio_catalog_lookup(
    apps: List[AppInput], save_path: Optional[str] = None
) -> Dict[str, Any]:
    """Look up all apps against Composio's real toolkit catalog."""
    client = get_client()
    if client is None:
        logger.warning("No COMPOSIO_API_KEY configured — skipping catalog lookup")
        return {}

    results: Dict[str, Any] = {}
    found = 0
    for app in apps:
        summary = lookup_toolkit(client, app.name)
        results[app.name] = summary
        if summary:
            found += 1
            logger.info(
                f"  ✓ {app.name}: Composio toolkit '{summary['slug']}' — "
                f"{summary['tools_count']} tools, auth={summary['auth_methods']}"
            )
        else:
            logger.info(f"  – {app.name}: no Composio toolkit found")

    logger.info(
        f"Composio catalog lookup complete: {found}/{len(apps)} apps already "
        f"have a Composio toolkit"
    )

    if save_path:
        save_json(results, save_path)

    return results


if __name__ == "__main__":
    from agent.config import INPUT_DIR, RAW_DIR
    from agent.utils import load_json, setup_logging

    setup_logging()
    raw_apps = load_json(INPUT_DIR / "apps_100.json")
    apps = [AppInput(**a) for a in raw_apps]
    run_composio_catalog_lookup(apps, save_path=str(RAW_DIR / "composio_catalog.json"))
