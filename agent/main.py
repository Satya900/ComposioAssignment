"""
Orchestrator: main.py

Runs the complete Composio App Research Agent pipeline:
1. Load 100 apps from input JSON
2. Pilot run (5 apps) → validate
3. Full research run → scrape docs for all 100
4. LLM classification → extract structured data
5. Verification pipeline → 3 layers + corrections
6. Pattern analysis → generate insights
7. Finalize → save production data
8. Generate HTML → create the deliverable page
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from agent.config import (
    CLASSIFIED_DIR,
    FINAL_DIR,
    INPUT_DIR,
    LOG_FILE,
    LOG_LEVEL,
    RAW_DIR,
    VERIFICATION_DIR,
)
from agent.schemas import AppInput, AppResearchResult
from agent.utils import (
    format_duration,
    get_logger,
    load_json,
    save_json,
    setup_logging,
)


async def main(pilot_only: bool = False, skip_research: bool = False, skip_verify: bool = False):
    """Run the complete research pipeline."""

    logger = setup_logging(level=LOG_LEVEL, log_file=LOG_FILE)

    start_time = time.time()
    logger.info("=" * 60)
    logger.info("🚀 COMPOSIO APP RESEARCH AGENT — Starting Pipeline")
    logger.info("=" * 60)

    # ─── LOAD INPUT ──────────────────────────────────────────────────────

    apps_path = INPUT_DIR / "apps_100.json"
    raw_apps = load_json(apps_path)
    apps = [AppInput(**app) for app in raw_apps]
    logger.info(f"📋 Loaded {len(apps)} apps from {apps_path}")

    # ─── PILOT RUN (optional) ────────────────────────────────────────────

    if pilot_only:
        logger.info("\n--- 🧪 PILOT RUN: Testing on 5 apps ---")
        pilot_apps = _select_pilot_apps(apps)
        logger.info(f"Pilot apps: {[a.name for a in pilot_apps]}")

        from agent.researcher import run_research_pipeline
        pilot_raw = await run_research_pipeline(
            pilot_apps, save_path=str(RAW_DIR / "pilot_raw.json")
        )

        from agent.classifier import run_classification_pipeline
        pilot_results, pilot_failures = await run_classification_pipeline(
            pilot_apps, pilot_raw,
            save_path=str(CLASSIFIED_DIR / "pilot_results.json"),
        )

        logger.info(f"\n🧪 Pilot complete: {len(pilot_results)} success, {len(pilot_failures)} failed")
        logger.info("⚠️  Review pilot results before running full pipeline.")

        elapsed = time.time() - start_time
        logger.info(f"⏱️  Pilot took {format_duration(elapsed)}")
        return

    # ─── STAGE 1: WEB RESEARCH ───────────────────────────────────────────

    if not skip_research:
        from agent.researcher import run_research_pipeline
        raw_data = await run_research_pipeline(apps)
    else:
        logger.info("⏭️  Skipping research (loading from disk)")
        raw_path = RAW_DIR / "research_raw.json"
        if raw_path.exists():
            from agent.schemas import RawResearchData
            raw_json = load_json(raw_path)
            raw_data = [RawResearchData(**rd) for rd in raw_json]
        else:
            logger.error(f"No research data found at {raw_path}")
            return

    # ─── STAGE 2: LLM CLASSIFICATION ────────────────────────────────────

    from agent.classifier import run_classification_pipeline
    results, failures = await run_classification_pipeline(apps, raw_data)

    # Save first-pass results
    save_json(
        [r.model_dump() for r in results],
        str(CLASSIFIED_DIR / "results_v1.json"),
    )
    logger.info(f"First pass: {len(results)} success, {len(failures)} failed")

    # ─── STAGE 3: VERIFICATION ───────────────────────────────────────────

    if not skip_verify:
        from agent.verifier import run_full_verification
        accuracy_report, corrections = await run_full_verification(results, raw_data)

        # Save corrected results
        save_json(
            [r.model_dump() for r in results],
            str(CLASSIFIED_DIR / "results_v2.json"),
        )

        logger.info(
            f"\n📊 Accuracy: {accuracy_report.first_pass_accuracy}% → "
            f"{accuracy_report.final_accuracy}% "
            f"(+{accuracy_report.improvement_delta}%)"
        )
    else:
        logger.info("⏭️  Skipping verification")
        accuracy_report = None

    # ─── STAGE 4: PATTERN ANALYSIS ───────────────────────────────────────

    from agent.pattern_analyzer import analyze_patterns
    patterns = analyze_patterns(results)

    # ─── FINALIZE ────────────────────────────────────────────────────────

    # Save final results
    save_json(
        [r.model_dump() for r in results],
        str(FINAL_DIR / "final_results.json"),
    )

    # Save accuracy report alongside final results
    if accuracy_report:
        save_json(
            accuracy_report.model_dump(),
            str(FINAL_DIR / "accuracy_report.json"),
        )

    # ─── GENERATE HTML ───────────────────────────────────────────────────

    logger.info("\n--- 🌐 GENERATING HTML REPORT ---")
    from agent.html_generator import generate_html_report
    generate_html_report(results, patterns, accuracy_report)

    # ─── DONE ────────────────────────────────────────────────────────────

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ PIPELINE COMPLETE in {format_duration(elapsed)}")
    logger.info(f"  📋 Apps researched:    {len(results)}/100")
    if accuracy_report:
        logger.info(f"  📊 Final accuracy:     {accuracy_report.final_accuracy}%")
    logger.info(f"  💡 Insights generated: {len(patterns.insights)}")
    logger.info(f"  🌐 HTML report:        site/index.html")
    logger.info(f"{'='*60}")


def _select_pilot_apps(apps: list[AppInput]) -> list[AppInput]:
    """Select 5 diverse pilot apps (1 from each of 5 different categories)."""
    categories_seen = set()
    pilot = []
    for app in apps:
        if app.category not in categories_seen and len(pilot) < 5:
            pilot.append(app)
            categories_seen.add(app.category)
    return pilot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Composio App Research Agent")
    parser.add_argument("--pilot", action="store_true", help="Run pilot on 5 apps only")
    parser.add_argument("--skip-research", action="store_true", help="Skip web research (use cached data)")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification pipeline")
    args = parser.parse_args()

    asyncio.run(main(
        pilot_only=args.pilot,
        skip_research=args.skip_research,
        skip_verify=args.skip_verify,
    ))
