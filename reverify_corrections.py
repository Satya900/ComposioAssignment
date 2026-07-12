"""
One-off: the full Stage 3 re-verification pass (meant to confirm the 8
corrections applied after first-pass Layer 2) almost entirely failed with
"No LLM provider configured" — both Groq's daily quota and OpenRouter's rate
limit were exhausted by that point in the run. Rather than redo the whole
Stage 3 pipeline (which would waste the first-pass Layer 2 sample that
already succeeded), this targets just the re-verification step: re-check the
corrected apps + a fresh random sample, recompute accuracy, and patch
accuracy_report.json (keeping first_pass_accuracy as-is — that measurement
was real) before regenerating the report.
"""

import asyncio

from agent.config import CLASSIFIED_DIR, FINAL_DIR, RAW_DIR, VERIFICATION_DIR
from agent.html_generator import generate_html_report
from agent.pattern_analyzer import analyze_patterns
from agent.schemas import AccuracyReport, AppResearchResult, RawResearchData
from agent.utils import get_logger, load_json, save_json, setup_logging
from agent.verifier import calculate_accuracy, run_verification_agent


async def main():
    setup_logging()
    logger = get_logger()

    results = [AppResearchResult(**r) for r in load_json(FINAL_DIR / "final_results.json")]
    raw_data = [RawResearchData(**rd) for rd in load_json(RAW_DIR / "research_raw.json")]
    corrections = load_json(VERIFICATION_DIR / "corrections.json")
    corrected_apps = sorted({c["app"] for c in corrections})
    logger.info(f"Re-verifying {len(corrected_apps)} corrected apps + a fresh 15-app random sample")

    old_accuracy = AccuracyReport(**load_json(FINAL_DIR / "accuracy_report.json"))

    re_verifications = await run_verification_agent(
        results, raw_data, sample_size=15, flagged_apps=corrected_apps,
    )

    succeeded = [v for v in re_verifications if v.fields_checked]
    failed = [v for v in re_verifications if not v.fields_checked]
    logger.info(f"Re-verification: {len(succeeded)} apps got real data, {len(failed)} failed (no LLM available)")

    if not succeeded:
        logger.error("Still 0 apps with real verification data — provider quota likely still exhausted. Not patching accuracy_report.json.")
        return

    final_accuracy = calculate_accuracy(re_verifications)
    final_accuracy.first_pass_accuracy = old_accuracy.first_pass_accuracy
    final_accuracy.final_accuracy = final_accuracy.overall_accuracy
    final_accuracy.improvement_delta = round(final_accuracy.overall_accuracy - old_accuracy.first_pass_accuracy, 1)

    logger.info(
        f"First-pass: {final_accuracy.first_pass_accuracy}% -> "
        f"Final: {final_accuracy.final_accuracy}% "
        f"(+{final_accuracy.improvement_delta}%), sample_size={final_accuracy.sample_size}"
    )

    save_json(final_accuracy.model_dump(), str(FINAL_DIR / "accuracy_report.json"))
    save_json([v.model_dump() for v in re_verifications], str(VERIFICATION_DIR / "verification_results.json"))

    patterns = analyze_patterns(results)
    save_json(patterns.model_dump(), str(FINAL_DIR / "patterns.json"))

    output_path = generate_html_report(results, patterns, accuracy=final_accuracy)
    logger.info(f"Final HTML report written to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
