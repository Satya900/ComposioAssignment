"""
One-off: build the final HTML report from the completed 100-app
data/classified/results_v1.json, without re-running research/classification.
Skips the verification stage (no accuracy section) — run agent.verifier
separately first if an accuracy report is wanted in the page.
"""

from agent.composio_lookup import enrich_results_with_catalog
from agent.config import CLASSIFIED_DIR, FINAL_DIR, RAW_DIR
from agent.html_generator import generate_html_report
from agent.pattern_analyzer import analyze_patterns
from agent.schemas import AppResearchResult
from agent.utils import get_logger, load_json, save_json, setup_logging


def main():
    setup_logging()
    logger = get_logger()

    raw_results = load_json(CLASSIFIED_DIR / "results_v1.json")
    results = [AppResearchResult(**r) for r in raw_results]
    logger.info(f"Loaded {len(results)}/100 classified apps")

    catalog_path = RAW_DIR / "composio_catalog.json"
    if catalog_path.exists():
        matched = enrich_results_with_catalog(results, load_json(catalog_path))
        logger.info(f"Composio catalog: {matched}/{len(results)} apps already exist as Composio toolkits")

    patterns = analyze_patterns(results)
    logger.info(f"Generated {len(patterns.insights)} insights")

    save_json([r.model_dump() for r in results], str(FINAL_DIR / "final_results.json"))
    save_json(patterns.model_dump(), str(FINAL_DIR / "patterns.json"))

    output_path = generate_html_report(results, patterns, accuracy=None)
    logger.info(f"HTML report written to {output_path}")


if __name__ == "__main__":
    main()
