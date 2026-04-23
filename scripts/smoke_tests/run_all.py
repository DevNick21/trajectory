"""Smoke-test runner.

Usage:
    python -m scripts.smoke_tests.run_all --list
    python -m scripts.smoke_tests.run_all --cheap
    python -m scripts.smoke_tests.run_all --only verdict,gov_data
    python -m scripts.smoke_tests.run_all --skip phase4_cv,scraper
    python -m scripts.smoke_tests.run_all                # run everything

Results are printed as they land; a rollup + total estimated cost is
printed at the end. Exits non-zero if any test fails.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import sys
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
    cheap: bool  # True when the test makes no paid LLM calls


_REGISTRY: list[_Entry] = [
    _Entry("gov_data",           "scripts.smoke_tests.gov_data",           cheap=True),
    _Entry("jsonld_extractor",   "scripts.smoke_tests.jsonld_extractor",   cheap=True),
    _Entry("content_shield",     "scripts.smoke_tests.content_shield",     cheap=False),
    _Entry("onboarding_parser",  "scripts.smoke_tests.onboarding_parser",  cheap=False),
    _Entry("intent_router",      "scripts.smoke_tests.intent_router",      cheap=False),
    _Entry("bot_boot",           "scripts.smoke_tests.bot_boot",           cheap=False),
    _Entry("scraper",            "scripts.smoke_tests.scraper",            cheap=False),
    _Entry("verdict",            "scripts.smoke_tests.verdict",            cheap=False),
    _Entry("phase4_cv",          "scripts.smoke_tests.phase4_cv",          cheap=False),
    # Managed Agents path: gated behind SMOKE_MANAGED_AGENTS=1 inside
    # the test body itself; runs ~$1-3 when enabled, no-ops otherwise.
    _Entry("managed_investigator", "scripts.smoke_tests.managed_investigator", cheap=False),
    # Agentic CV tailor: gated behind SMOKE_AGENTIC_CV=1 (~$0.35).
    _Entry("cv_tailor_agentic",  "scripts.smoke_tests.cv_tailor_agentic",  cheap=False),
    # LaTeX CV: gated behind SMOKE_LATEX=1; needs pdflatex on PATH.
    _Entry("cv_latex",           "scripts.smoke_tests.cv_latex",           cheap=False),
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
            print(f"{e.name:<20} [{tag}]  {e.module}")
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
    if args.cheap:
        selected = [e for e in selected if e.cheap]
    return selected


async def _run(selected: list[_Entry], fail_fast: bool):
    results = []
    total_cost = 0.0
    for entry in selected:
        module = importlib.import_module(entry.module)
        result = await module.run()
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Trajectory smoke tests.")
    parser.add_argument("--list", action="store_true", help="List registered tests and exit.")
    parser.add_argument("--only", help="Comma-separated tests to run (whitelist).")
    parser.add_argument("--skip", help="Comma-separated tests to skip.")
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
        print(f"  - {e.name}")
    print()

    results, total_cost = asyncio.run(_run(selected, args.fail_fast))

    print()
    print("=" * 60)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    print(f"{passed} passed, {failed} failed   (est. spend ~${total_cost:.2f})")
    for r in results:
        print(f"  {r.summary()}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
