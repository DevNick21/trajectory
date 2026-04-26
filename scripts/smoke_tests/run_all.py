"""Smoke-test runner.

Usage:
    python -m scripts.smoke_tests.run_all --list
    python -m scripts.smoke_tests.run_all --cheap
    python -m scripts.smoke_tests.run_all --category infra,validator
    python -m scripts.smoke_tests.run_all --only verdict,gov_data
    python -m scripts.smoke_tests.run_all --skip phase4_cv,scraper
    python -m scripts.smoke_tests.run_all                # run everything

Results are printed as they land; a rollup (including per-category
subtotals) + total estimated cost is printed at the end. Exits
non-zero if any test fails.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Ensure sys.path has src/ BEFORE any trajectory imports land from the
# individual smoke modules.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Windows console is cp1252 by default — coerce stdout to UTF-8 so the
# occasional Unicode glyph in a log line doesn't crash the run.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover
        pass


# Ordered from cheap to expensive so `Ctrl+C`-on-first-fail costs least.
@dataclass(frozen=True)
class _Entry:
    name: str
    module: str
    cheap: bool            # True when the test makes no paid LLM calls
    category: str          # infra, validator, renderer, api, phase1,
                           # phase4, agent-util, e2e


_REGISTRY: list[_Entry] = [
    # ── infra (no LLM) ─────────────────────────────────────────────────
    _Entry("storage_crud",       "scripts.smoke_tests.storage_crud",       cheap=True,  category="infra"),
    _Entry("faiss_retrieval",    "scripts.smoke_tests.faiss_retrieval",    cheap=True,  category="infra"),
    _Entry("ratelimit",          "scripts.smoke_tests.ratelimit",          cheap=True,  category="infra"),
    _Entry("data_freshness",     "scripts.smoke_tests.data_freshness",     cheap=True,  category="infra"),
    _Entry("observability",      "scripts.smoke_tests.observability",      cheap=True,  category="infra"),

    # ── validator (no LLM) ─────────────────────────────────────────────
    _Entry("validators_citations",         "scripts.smoke_tests.validators_citations",         cheap=True, category="validator"),
    _Entry("validators_banned_phrases",    "scripts.smoke_tests.validators_banned_phrases",    cheap=True, category="validator"),
    _Entry("validators_pii_scrubber",      "scripts.smoke_tests.validators_pii_scrubber",      cheap=True, category="validator"),
    _Entry("validators_content_shield_tier1", "scripts.smoke_tests.validators_content_shield_tier1", cheap=True, category="validator"),
    _Entry("validators_schema_retry",      "scripts.smoke_tests.validators_schema_retry",      cheap=True, category="validator"),

    # ── renderer (no LLM) ──────────────────────────────────────────────
    _Entry("renderers_cv_docx",            "scripts.smoke_tests.renderers_cv_docx",            cheap=True, category="renderer"),
    _Entry("renderers_cv_pdf",             "scripts.smoke_tests.renderers_cv_pdf",             cheap=True, category="renderer"),
    _Entry("renderers_cover_letter_docx",  "scripts.smoke_tests.renderers_cover_letter_docx",  cheap=True, category="renderer"),
    _Entry("renderers_cover_letter_pdf",   "scripts.smoke_tests.renderers_cover_letter_pdf",   cheap=True, category="renderer"),

    # ── api (FastAPI TestClient, mostly no LLM) ────────────────────────
    _Entry("api_boot",           "scripts.smoke_tests.api_boot",           cheap=True,  category="api"),
    _Entry("api_profile",        "scripts.smoke_tests.api_profile",        cheap=True,  category="api"),
    _Entry("api_sessions",       "scripts.smoke_tests.api_sessions",       cheap=True,  category="api"),
    _Entry("api_queue",          "scripts.smoke_tests.api_queue",          cheap=True,  category="api"),
    _Entry("api_onboarding",     "scripts.smoke_tests.api_onboarding",     cheap=True,  category="api"),
    _Entry("api_pack",           "scripts.smoke_tests.api_pack",           cheap=True,  category="api"),

    # ── phase1 — gov data + extractor agents ───────────────────────────
    _Entry("gov_data",           "scripts.smoke_tests.gov_data",           cheap=True,  category="phase1"),
    _Entry("jsonld_extractor",   "scripts.smoke_tests.jsonld_extractor",   cheap=True,  category="phase1"),
    _Entry("salary_data",        "scripts.smoke_tests.salary_data",        cheap=True,  category="phase1"),
    _Entry("ghost_job",          "scripts.smoke_tests.ghost_job",          cheap=False, category="phase1"),
    _Entry("red_flags",          "scripts.smoke_tests.red_flags",          cheap=False, category="phase1"),
    _Entry("style_extractor",    "scripts.smoke_tests.style_extractor",    cheap=False, category="phase1"),

    # ── LLM-backed: onboarding, intent, shield tier2 ───────────────────
    _Entry("content_shield",     "scripts.smoke_tests.content_shield",     cheap=False, category="agent-util"),
    _Entry("onboarding_parser",  "scripts.smoke_tests.onboarding_parser",  cheap=False, category="agent-util"),
    _Entry("intent_router",      "scripts.smoke_tests.intent_router",      cheap=False, category="agent-util"),
    _Entry("question_designer",  "scripts.smoke_tests.question_designer",  cheap=False, category="agent-util"),
    _Entry("star_polisher",      "scripts.smoke_tests.star_polisher",      cheap=False, category="agent-util"),
    _Entry("self_audit",         "scripts.smoke_tests.self_audit",         cheap=False, category="agent-util"),
    _Entry("prompt_auditor",     "scripts.smoke_tests.prompt_auditor",     cheap=False, category="agent-util"),

    # ── phase4 generators ──────────────────────────────────────────────
    _Entry("cover_letter",       "scripts.smoke_tests.cover_letter",       cheap=False, category="phase4"),
    _Entry("likely_questions",   "scripts.smoke_tests.likely_questions",   cheap=False, category="phase4"),
    _Entry("salary_strategist",  "scripts.smoke_tests.salary_strategist",  cheap=False, category="phase4"),
    _Entry("draft_reply",        "scripts.smoke_tests.draft_reply",        cheap=False, category="phase4"),

    # ── e2e: bot boot + full pipelines ─────────────────────────────────
    # Cheap journey tests — full orchestrator wiring with fixture-driven
    # Phase 1 sub-agents and a mocked verdict. No live LLM calls.
    _Entry("forward_journey_uk",            "scripts.smoke_tests.forward_journey_uk",            cheap=True,  category="e2e"),
    _Entry("forward_journey_visa_block",    "scripts.smoke_tests.forward_journey_visa_block",    cheap=True,  category="e2e"),
    _Entry("bot_draft_cv_files",            "scripts.smoke_tests.bot_draft_cv_files",            cheap=True,  category="e2e"),
    _Entry("bot_read_intents",              "scripts.smoke_tests.bot_read_intents",              cheap=True,  category="e2e"),
    _Entry("bot_analyse_offer_text",        "scripts.smoke_tests.bot_analyse_offer_text",        cheap=True,  category="e2e"),
    _Entry("onboarding_journey_uk",         "scripts.smoke_tests.onboarding_journey_uk",         cheap=True,  category="e2e"),
    _Entry("onboarding_journey_visa",       "scripts.smoke_tests.onboarding_journey_visa",       cheap=True,  category="e2e"),
    _Entry("onboarding_persona_stress",     "scripts.smoke_tests.onboarding_persona_stress",     cheap=True,  category="e2e"),
    _Entry("bot_boot",           "scripts.smoke_tests.bot_boot",           cheap=False, category="e2e"),
    _Entry("scraper",            "scripts.smoke_tests.scraper",            cheap=False, category="e2e"),
    _Entry("verdict",            "scripts.smoke_tests.verdict",            cheap=False, category="e2e"),
    _Entry("phase4_cv",          "scripts.smoke_tests.phase4_cv",          cheap=False, category="e2e"),
    # Managed Agents paths — each gated behind its own SMOKE_* env var
    # inside the test body; runs ~$1-3 when enabled, no-ops otherwise.
    _Entry("managed_investigator",  "scripts.smoke_tests.managed_investigator",  cheap=False, category="e2e"),
    _Entry("managed_reviews",       "scripts.smoke_tests.managed_reviews",       cheap=False, category="e2e"),
    _Entry("verdict_deep_research", "scripts.smoke_tests.verdict_deep_research", cheap=False, category="e2e"),
    _Entry("e2e_live_stress",       "scripts.smoke_tests.e2e_live_stress",       cheap=False, category="e2e"),
    # Agentic CV tailor: gated behind SMOKE_AGENTIC_CV=1 (~$0.35).
    _Entry("cv_tailor_agentic",  "scripts.smoke_tests.cv_tailor_agentic",  cheap=False, category="e2e"),
    # LaTeX CV: gated behind SMOKE_LATEX=1; needs pdflatex on PATH.
    _Entry("cv_latex",           "scripts.smoke_tests.cv_latex",           cheap=False, category="e2e"),
]


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Silence noisy third-party loggers unless --verbose.
    if not verbose:
        for noisy in ("httpx", "httpcore", "anthropic", "telegram",
                      "urllib3", "filelock", "sentence_transformers"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _select(args) -> list[_Entry]:
    if args.list:
        for e in _REGISTRY:
            tag = "cheap" if e.cheap else "paid"
            print(f"{e.name:<28} [{tag:<5} / {e.category:<10}]  {e.module}")
        sys.exit(0)

    selected = list(_REGISTRY)
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        unknown = wanted - {e.name for e in selected}
        if unknown:
            print(f"unknown smoke test(s): {sorted(unknown)}")
            sys.exit(2)
        selected = [e for e in selected if e.name in wanted]
    if args.skip:
        skip = {n.strip() for n in args.skip.split(",") if n.strip()}
        selected = [e for e in selected if e.name not in skip]
    if args.category:
        cats = {c.strip() for c in args.category.split(",") if c.strip()}
        all_cats = {e.category for e in _REGISTRY}
        unknown_cats = cats - all_cats
        if unknown_cats:
            print(
                f"unknown category/ies: {sorted(unknown_cats)} "
                f"(known: {sorted(all_cats)})"
            )
            sys.exit(2)
        selected = [e for e in selected if e.category in cats]
    if args.cheap:
        selected = [e for e in selected if e.cheap]
    return selected


def _read_actual_cost_from_log() -> "float | None":
    """Pull the real spend from the per-run SQLite cost log.

    Each smoke test calls `prepare_environment()` which redirects
    `settings.sqlite_db_path` to a tempdir; every `log_llm_cost(...)`
    call from `llm.py` writes a row there with the actual token-derived
    USD via `storage.estimate_cost_usd`. We read the sum at rollup time.

    Returns None when the cost log table doesn't exist (e.g. no test
    initialised storage in this run, or storage init was skipped).
    """
    try:
        import asyncio as _asyncio
        from trajectory.storage import total_cost_usd
        return _asyncio.run(total_cost_usd())
    except Exception:
        return None


async def _run(selected: list[_Entry], fail_fast: bool):
    results = []
    total_cost = 0.0
    for entry in selected:
        module = importlib.import_module(entry.module)
        result = await module.run()
        # Tag the result with category so the rollup can subtotal.
        result.__dict__["category"] = entry.category
        print(result.summary())
        for m in result.messages:
            print("   -", m)
        for f in result.failures:
            print("   FAIL:", f)
        if result.error:
            print("   TRACE:", result.error.splitlines()[-1])
        total_cost += result.estimated_cost_usd
        results.append(result)
        if fail_fast and not result.passed:
            break
    return results, total_cost


def _print_rollup(results, total_cost: float) -> None:
    print()
    print("=" * 60)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    # Hand-set ESTIMATED_COST_USD constants summed across tests — useful
    # for "what should this run cost?" planning. The real per-call cost
    # comes from `storage.total_cost_usd()` which reads the SQLite cost
    # log populated by every `log_llm_cost(...)` call. Show both so
    # drift between budget and actual is visible.
    actual_cost = _read_actual_cost_from_log()
    if actual_cost is None:
        print(f"{passed} passed, {failed} failed   (est. spend ~${total_cost:.2f})")
    else:
        delta = actual_cost - total_cost
        sign = "+" if delta >= 0 else ""
        print(
            f"{passed} passed, {failed} failed   "
            f"(budget ~${total_cost:.2f}; actual ${actual_cost:.4f}; "
            f"delta {sign}${delta:.4f})"
        )

    # Per-category subtotals.
    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        cat = getattr(r, "category", "unknown")
        by_cat[cat].append(r)
    print()
    print("By category:")
    for cat in sorted(by_cat):
        cat_results = by_cat[cat]
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_failed = sum(1 for r in cat_results if not r.passed)
        cat_cost = sum(r.estimated_cost_usd for r in cat_results)
        status = "✓" if cat_failed == 0 else "✗"
        print(
            f"  {status} {cat:<12} {cat_passed:>2}/{len(cat_results):<2} "
            f"passed   (~${cat_cost:.2f})"
        )

    print()
    print("Details:")
    for r in results:
        print(f"  {r.summary()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Trajectory smoke tests.")
    parser.add_argument("--list", action="store_true", help="List registered tests and exit.")
    parser.add_argument("--only", help="Comma-separated tests to run (whitelist).")
    parser.add_argument("--skip", help="Comma-separated tests to skip.")
    parser.add_argument(
        "--category",
        help="Comma-separated categories to run (infra, validator, renderer, "
             "api, phase1, phase4, agent-util, e2e).",
    )
    parser.add_argument(
        "--cheap", action="store_true",
        help="Only run tests that make no paid LLM calls.",
    )
    parser.add_argument(
        "--fail-fast", action="store_true",
        help="Stop on first failure to save credits during debugging.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    selected = _select(args)
    if not selected:
        print("No smoke tests selected.")
        return 2

    print(f"Running {len(selected)} smoke test(s):")
    for e in selected:
        print(f"  - {e.name}  [{e.category}]")
    print()

    results, total_cost = asyncio.run(_run(selected, args.fail_fast))
    _print_rollup(results, total_cost)

    failed = sum(1 for r in results if not r.passed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
