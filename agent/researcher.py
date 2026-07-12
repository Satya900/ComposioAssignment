"""
Stage 1: Web Research Agent

For each of the 100 apps, discovers and scrapes developer documentation pages
to extract raw information about auth, API, and access model.

Primary tool: Firecrawl + direct HTTP
Also checks for existing MCP servers via GitHub and npm.

Composio's SDK is used separately (see agent/composio_lookup.py) — not here.
The current `composio` package (as opposed to the deprecated `composio-core`
this file used to import) has no generic "search the web" / "scrape a URL"
action; it exposes Composio's own toolkit catalog for building agent tools.
That is a first-party ground-truth source in its own right (real auth
schemes + tool/trigger counts per app), so it is used as a dedicated
cross-check input rather than bolted onto this generic docs scraper.
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import (
    FIRECRAWL_API_KEY,
    GITHUB_TOKEN,
    PROBLEM_APPS,
    REQUEST_TIMEOUT,
    RESEARCH_CONCURRENCY,
    RETRY_ATTEMPTS,
    RETRY_DELAY_BASE,
    SCRAPE_MAX_TOKENS,
)
from agent.schemas import AppInput, RawResearchData
from agent.utils import (
    clean_text,
    console,
    create_progress_bar,
    generate_docs_urls,
    get_logger,
    now_iso,
    save_json,
    truncate_text,
)

logger = get_logger()


# ─── COMPOSIO SDK RESEARCH (deprecated path, kept as a documented no-op) ────


async def research_with_composio(app_name: str, website: str) -> Dict[str, Any]:
    """
    Historical primary research path. The `composio-core` / ComposioToolSet
    API this used to call is deprecated and no longer installable in a way
    that matches this code (see module docstring). Real Composio SDK usage
    now lives in agent/composio_lookup.py, which queries Composio's current
    toolkit catalog directly. This function is kept only so the Stage 1
    fallback chain below (Firecrawl -> direct HTTP) needs no further changes.
    """
    return {"app_name": app_name, "docs_pages": [], "research_method": "composio_unavailable"}


# ─── FIRECRAWL FALLBACK ─────────────────────────────────────────────────────


async def research_with_firecrawl(app_name: str, website: str) -> Dict[str, Any]:
    """
    Fallback research using Firecrawl for docs scraping.
    Tries common docs URL patterns, then falls back to search.
    """
    docs_pages = []

    if not FIRECRAWL_API_KEY:
        logger.warning(f"No Firecrawl API key, skipping Firecrawl for {app_name}")
        return {"app_name": app_name, "docs_pages": [], "research_method": "firecrawl_no_key"}

    try:
        # firecrawl-py v4 exposes the legacy, synchronous scrape/search API
        # through V1FirecrawlApp.  FirecrawlApp is now a v2 parse-only alias.
        from firecrawl import V1FirecrawlApp

        firecrawl = V1FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        # Try common docs URL patterns.  These are a fast first pass; targeted
        # search below fills the auth/reference gaps that landing pages miss.
        candidate_urls = generate_docs_urls(website)

        for url in candidate_urls[:3]:
            try:
                result = firecrawl.scrape_url(url, formats=["markdown"])
                markdown = (
                    getattr(result, "markdown", None)
                    if result is not None else None
                )
                if markdown is None and isinstance(result, dict):
                    markdown = result.get("markdown")
                if markdown:
                    content = clean_text(markdown)
                    if len(content) > 100:  # Skip near-empty pages
                        docs_pages.append({
                            "url": url,
                            "content": truncate_text(content, SCRAPE_MAX_TOKENS),
                        })
                        if len(docs_pages) >= 3:
                            break
            except Exception as e:
                logger.debug(f"Firecrawl scrape failed for {url}: {e}")
                continue

        # Always supplement landing/reference pages with targeted search.  The
        # assignment needs auth, access, and API evidence, not just one page.
        try:
            search_result = firecrawl.search(
                f"{app_name} official API authentication documentation",
                limit=5,
            )
            items = getattr(search_result, "data", search_result)
            existing_urls = {page["url"] for page in docs_pages}
            if isinstance(items, list):
                for item in items:
                    url = getattr(item, "url", "")
                    content = getattr(item, "markdown", "") or getattr(item, "content", "")
                    if isinstance(item, dict):
                        url = item.get("url", url)
                        content = item.get("markdown", content) or item.get("content", content)
                    if not url or url in existing_urls:
                        continue
                    if not content:
                        scraped = firecrawl.scrape_url(url, formats=["markdown"])
                        content = getattr(scraped, "markdown", "")
                    if content and len(content) > 100:
                        docs_pages.append({
                            "url": url,
                            "content": truncate_text(clean_text(content), SCRAPE_MAX_TOKENS),
                        })
                        existing_urls.add(url)
                    if len(docs_pages) >= 5:
                        break
        except Exception as e:
            logger.debug(f"Firecrawl search failed for {app_name}: {e}")

    except ImportError:
        logger.warning("Firecrawl not installed")
    except Exception as e:
        logger.warning(f"Firecrawl research failed for {app_name}: {e}")

    return {
        "app_name": app_name,
        "docs_pages": docs_pages,
        "research_method": "firecrawl_fallback",
        "research_timestamp": now_iso(),
    }


# ─── DIRECT HTTP SCRAPING (last resort) ─────────────────────────────────────


async def research_with_http(app_name: str, website: str) -> Dict[str, Any]:
    """
    Direct HTTP scraping as a last resort.
    Fetches raw HTML from common docs URLs and extracts text.
    """
    docs_pages = []
    candidate_urls = generate_docs_urls(website)

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "ComposioResearchAgent/1.0 (research project)"},
    ) as client:
        for url in candidate_urls[:5]:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    content = resp.text
                    # Basic HTML to text conversion
                    text = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
                    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = clean_text(text)

                    if len(text) > 200:
                        docs_pages.append({
                            "url": url,
                            "content": truncate_text(text, SCRAPE_MAX_TOKENS),
                        })
                        if len(docs_pages) >= 2:
                            break
            except Exception as e:
                logger.debug(f"HTTP scrape failed for {url}: {e}")
                continue

    return {
        "app_name": app_name,
        "docs_pages": docs_pages,
        "research_method": "http_direct",
        "research_timestamp": now_iso(),
    }


# ─── MCP EXISTENCE CHECK ────────────────────────────────────────────────────


async def check_mcp_existence(app_name: str) -> Dict[str, Any]:
    """
    Check if an MCP server already exists for this app.
    Searches GitHub and npm registry.
    """
    normalized = app_name.lower().replace(" ", "-").replace(".", "")

    github_repos = []
    npm_packages = []

    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    headers["Accept"] = "application/vnd.github.v3+json"

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        # Check 1: GitHub search
        try:
            search_queries = [
                f"{normalized} MCP server",
                f"mcp-{normalized}",
                f"{normalized}-mcp",
            ]
            for query in search_queries:
                resp = await client.get(
                    "https://api.github.com/search/repositories",
                    params={"q": query, "per_page": 5, "sort": "stars"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for repo in data.get("items", []):
                        repo_info = {
                            "name": repo.get("full_name", ""),
                            "url": repo.get("html_url", ""),
                            "stars": repo.get("stargazers_count", 0),
                            "description": repo.get("description", ""),
                        }
                        # Check if it's actually MCP-related
                        desc = (repo.get("description", "") or "").lower()
                        name = (repo.get("name", "") or "").lower()
                        if "mcp" in desc or "mcp" in name or "model context protocol" in desc:
                            github_repos.append(repo_info)

                # Avoid rate limiting
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"GitHub MCP check failed for {app_name}: {e}")

        # Check 2: npm registry search
        try:
            npm_queries = [f"mcp-{normalized}", f"{normalized}-mcp", f"@mcp/{normalized}"]
            for query in npm_queries:
                resp = await client.get(
                    f"https://registry.npmjs.org/-/v1/search",
                    params={"text": query, "size": 3},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for pkg in data.get("objects", []):
                        pkg_info = pkg.get("package", {})
                        pkg_name = pkg_info.get("name", "").lower()
                        pkg_desc = (pkg_info.get("description", "") or "").lower()
                        if "mcp" in pkg_name or "mcp" in pkg_desc:
                            npm_packages.append({
                                "name": pkg_info.get("name", ""),
                                "version": pkg_info.get("version", ""),
                                "description": pkg_info.get("description", ""),
                                "url": f"https://www.npmjs.com/package/{pkg_info.get('name', '')}",
                            })
        except Exception as e:
            logger.debug(f"npm MCP check failed for {app_name}: {e}")

    # Deduplicate
    seen_repos = set()
    unique_repos = []
    for r in github_repos:
        if r["url"] not in seen_repos:
            seen_repos.add(r["url"])
            unique_repos.append(r)

    seen_pkgs = set()
    unique_pkgs = []
    for p in npm_packages:
        if p["name"] not in seen_pkgs:
            seen_pkgs.add(p["name"])
            unique_pkgs.append(p)

    exists = bool(unique_repos or unique_pkgs)

    return {
        "exists": exists,
        "github_repos": unique_repos[:3],
        "npm_packages": unique_pkgs[:3],
        "source": "github" if unique_repos else ("npm" if unique_pkgs else "none"),
    }


# ─── MAIN RESEARCH FUNCTION (per app) ───────────────────────────────────────


async def research_single_app(app: AppInput) -> RawResearchData:
    """
    Research a single app using all available methods.
    Tries Composio SDK first, then Firecrawl, then direct HTTP.
    Also checks for MCP existence.
    """
    app_name = app.name
    website = app.website
    errors = []

    logger.info(f"[{app.id:3d}/100] Researching: {app_name} ({website})")

    # Check if this is a known problem app
    if app_name in PROBLEM_APPS:
        logger.info(f"  ⚠️  Known tricky app: {PROBLEM_APPS[app_name]}")

    # Step 1: Try Composio SDK (primary)
    result = await research_with_composio(app_name, website)
    docs_pages = result.get("docs_pages", [])
    research_method = result.get("research_method", "composio_sdk")

    # Step 2: If Composio didn't get enough content, try Firecrawl
    if len(docs_pages) < 2 or all(len(p.get("content", "")) < 200 for p in docs_pages):
        logger.info(f"  → Falling back to Firecrawl for {app_name}")
        fallback = await research_with_firecrawl(app_name, website)
        if fallback.get("docs_pages"):
            docs_pages.extend(fallback["docs_pages"])
            research_method = "composio_plus_firecrawl"

    # Step 3: If still not enough, try direct HTTP
    if len(docs_pages) < 1 or all(len(p.get("content", "")) < 200 for p in docs_pages):
        logger.info(f"  → Falling back to direct HTTP for {app_name}")
        http_result = await research_with_http(app_name, website)
        if http_result.get("docs_pages"):
            docs_pages.extend(http_result["docs_pages"])
            research_method = "multi_fallback"

    # Step 4: Check for existing MCP server
    mcp_check = await check_mcp_existence(app_name)

    # Deduplicate docs pages by URL
    seen_urls = set()
    unique_pages = []
    for page in docs_pages:
        url = page.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_pages.append(page)

    # Log results
    total_content = sum(len(p.get("content", "")) for p in unique_pages)
    mcp_status = "✅ MCP found" if mcp_check.get("exists") else "❌ No MCP"
    logger.info(
        f"  ✓ {app_name}: {len(unique_pages)} pages, "
        f"{total_content:,} chars, {mcp_status}, method={research_method}"
    )

    return RawResearchData(
        app_name=app_name,
        website=website,
        docs_pages=unique_pages[:5],  # Keep top 5 pages
        mcp_check=mcp_check,
        research_method=research_method,
        research_timestamp=now_iso(),
        errors=errors,
    )


# ─── BATCH RESEARCH PIPELINE ────────────────────────────────────────────────


async def run_research_pipeline(
    apps: List[AppInput],
    save_path: Optional[str] = None,
) -> List[RawResearchData]:
    """
    Research all apps with concurrency control and progress tracking.
    Processes in batches of RESEARCH_CONCURRENCY, with checkpoints.
    """
    from agent.config import CHECKPOINT_EVERY_N, RAW_DIR

    results: List[RawResearchData] = []
    errors: List[Dict] = []

    save_path = save_path or str(RAW_DIR / "research_raw.json")

    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 1: WEB RESEARCH — {len(apps)} apps")
    logger.info(f"Concurrency: {RESEARCH_CONCURRENCY}, Timeout: {REQUEST_TIMEOUT}s")
    logger.info(f"{'='*60}\n")

    semaphore = asyncio.Semaphore(RESEARCH_CONCURRENCY)

    async def research_with_semaphore(app: AppInput) -> RawResearchData:
        async with semaphore:
            try:
                return await research_single_app(app)
            except Exception as e:
                logger.error(f"Fatal error researching {app.name}: {e}")
                errors.append({"app": app.name, "error": str(e)})
                return RawResearchData(
                    app_name=app.name,
                    website=app.website,
                    research_method="failed",
                    research_timestamp=now_iso(),
                    errors=[str(e)],
                )

    # Process in batches with checkpoints
    batch_size = RESEARCH_CONCURRENCY
    for batch_start in range(0, len(apps), batch_size):
        batch = apps[batch_start : batch_start + batch_size]

        batch_results = await asyncio.gather(
            *[research_with_semaphore(app) for app in batch]
        )
        results.extend(batch_results)

        # Progress
        done = min(batch_start + batch_size, len(apps))
        logger.info(f"\n📊 Progress: {done}/{len(apps)} apps researched\n")

        # Checkpoint save
        if done % CHECKPOINT_EVERY_N == 0 or done == len(apps):
            save_json(
                [r.model_dump() for r in results],
                save_path,
            )
            logger.info(f"💾 Checkpoint saved: {save_path}")

        # Rate limit pause between batches
        if done < len(apps):
            await asyncio.sleep(1)

    # Final save
    save_json([r.model_dump() for r in results], save_path)

    # Summary
    successful = sum(1 for r in results if r.docs_pages)
    no_docs = sum(1 for r in results if not r.docs_pages)
    has_mcp = sum(1 for r in results if r.mcp_check.get("exists", False))

    logger.info(f"\n{'='*60}")
    logger.info(f"STAGE 1 COMPLETE")
    logger.info(f"  ✅ With docs:    {successful}/{len(apps)}")
    logger.info(f"  ❌ No docs:      {no_docs}/{len(apps)}")
    logger.info(f"  🔗 Has MCP:      {has_mcp}/{len(apps)}")
    logger.info(f"  💾 Saved to:     {save_path}")
    logger.info(f"{'='*60}\n")

    return results
