"""
One-off: re-run Stage 2 classification only for apps that failed in the
first pass (data/classified/failures_v1.json), using the cached Stage 1
research (data/raw/research_raw.json) so no re-scraping is needed. Merges
successes into results_v1.json and rewrites failures_v1.json with whatever
still fails.
"""

import asyncio

from agent.config import CLASSIFIED_DIR, INPUT_DIR, RAW_DIR
from agent.classifier import run_classification_pipeline
from agent.schemas import AppInput, RawResearchData
from agent.utils import get_logger, load_json, save_json, setup_logging


async def main():
    setup_logging()
    logger = get_logger()

    apps_all = [AppInput(**a) for a in load_json(INPUT_DIR / "apps_100.json")]
    raw_all = [RawResearchData(**rd) for rd in load_json(RAW_DIR / "research_raw.json")]

    existing_results = load_json(CLASSIFIED_DIR / "results_v1.json")
    existing_failures = load_json(CLASSIFIED_DIR / "failures_v1.json")

    done_names = {r["name"] for r in existing_results}
    todo_apps = [a for a in apps_all if a.name not in done_names]

    logger.info(f"Already classified: {len(done_names)}/100. Retrying: {len(todo_apps)} apps.")

    new_results, new_failures = await run_classification_pipeline(
        todo_apps, raw_all, save_path=str(CLASSIFIED_DIR / "_retry_results.json")
    )

    merged_results = existing_results + [r.model_dump() for r in new_results]
    new_failure_names = {f["app"] for f in new_failures}
    # Keep only failures that are still unresolved
    merged_failures = [f for f in existing_failures if f["app"] in new_failure_names] + [
        f for f in new_failures
    ]
    # De-dupe by app name, keep latest
    merged_failures = list({f["app"]: f for f in merged_failures}.values())

    save_json(merged_results, str(CLASSIFIED_DIR / "results_v1.json"))
    save_json(merged_failures, str(CLASSIFIED_DIR / "failures_v1.json"))

    logger.info(
        f"\nMerge complete: {len(merged_results)}/100 classified, "
        f"{len(merged_failures)}/100 still failing."
    )


if __name__ == "__main__":
    asyncio.run(main())
