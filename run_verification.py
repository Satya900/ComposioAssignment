"""
One-off: run Stage 3 verification (3-layer: automated + agent + human
checklist) against the completed 100-app data/classified/results_v1.json,
reusing the cached Stage 1 research so no re-scraping is needed. Enriches
results with Composio's own toolkit-catalog data first (real ground truth,
no LLM cost) so Layer 1's Composio cross-check has it available. Applies
corrections in place, then regenerates the final HTML report with the real
accuracy numbers.
"""

import asyncio

from agent.composio_lookup import enrich_results_with_catalog
from agent.config import CLASSIFIED_DIR, FINAL_DIR, RAW_DIR
from agent.html_generator import generate_html_report
from agent.pattern_analyzer import analyze_patterns
from agent.schemas import AppResearchResult, RawResearchData
from agent.utils import get_logger, load_json, save_json, setup_logging
from agent.verifier import run_full_verification


async def main():
    setup_logging()
    logger = get_logger()

    results = [AppResearchResult(**r) for r in load_json(CLASSIFIED_DIR / "results_v1.json")]
    raw_data = [RawResearchData(**rd) for rd in load_json(RAW_DIR / "research_raw.json")]
    logger.info(f"Loaded {len(results)} classified apps, {len(raw_data)} raw research records")

    catalog = load_json(RAW_DIR / "composio_catalog.json")
    matched = enrich_results_with_catalog(results, catalog)
    logger.info(f"Composio catalog: {matched}/{len(results)} apps already exist as Composio toolkits")

    accuracy_report, corrections = await run_full_verification(results, raw_data)

    save_json([r.model_dump() for r in results], str(CLASSIFIED_DIR / "results_v2.json"))
    save_json([r.model_dump() for r in results], str(FINAL_DIR / "final_results.json"))
    save_json(accuracy_report.model_dump(), str(FINAL_DIR / "accuracy_report.json"))

    patterns = analyze_patterns(results)
    save_json(patterns.model_dump(), str(FINAL_DIR / "patterns.json"))

    output_path = generate_html_report(results, patterns, accuracy=accuracy_report)
    logger.info(f"\nFinal HTML report (with real accuracy data) written to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
