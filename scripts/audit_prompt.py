"""Build-time Prompt Auditor CLI.

AGENTS.md §17 + PROJECT_STRUCTURE.md `scripts/audit_prompt.py`.

Reads the target agent's `SYSTEM_PROMPT` constant from
`src/trajectory/sub_agents/<agent>.py`, infers its output schema from
the agent module, pairs it with a declared `INPUT_SOURCES` list
(trusted / untrusted labels), and calls the Prompt Auditor. Writes
each report to `./audits/<agent>_<timestamp>.json`.

Usage:
    python scripts/audit_prompt.py verdict
    python scripts/audit_prompt.py salary_strategist
    python scripts/audit_prompt.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Make `trajectory` importable regardless of where this script is run from.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pydantic import BaseModel  # noqa: E402

from trajectory.sub_agents import prompt_auditor  # noqa: E402

logger = logging.getLogger("audit_prompt")

# The 16 runtime agents that should be audited. Each row declares:
#   module_name         — file under src/trajectory/sub_agents/
#   system_prompt_attr  — attribute name holding the system prompt string
#   input_sources       — labelled trusted/untrusted inputs the agent sees
#
# System-prompt attribute defaults to `SYSTEM_PROMPT`; overrides are listed
# explicitly where the module uses a different constant name.
_AGENT_REGISTRY: dict[str, dict] = {
    "company_scraper_summariser": {
        "module": "trajectory.sub_agents.company_scraper",
        "system_prompt_attr": "COMPANY_SUMMARISER_SYSTEM_PROMPT",
        "output_schema_symbol": "CompanyResearch",
        "input_sources": [
            "job_url: TRUSTED",
            "company_domain: TRUSTED",
            "scraped_pages: UNTRUSTED",
        ],
    },
    "jd_extractor": {
        "module": "trajectory.sub_agents.company_scraper",
        "system_prompt_attr": "JD_EXTRACTOR_SYSTEM_PROMPT",
        "output_schema_symbol": "ExtractedJobDescription",
        "input_sources": [
            "job_url: TRUSTED",
            "posting_platform_hint: TRUSTED",
            "scraped_jd_text: UNTRUSTED",
        ],
    },
    "ghost_job_detector": {
        "module": "trajectory.sub_agents.ghost_job_detector",
        "system_prompt_attr": "JD_SCORER_SYSTEM_PROMPT",
        "output_schema_symbol": "GhostJobJDScore",
        "input_sources": [
            "role_title: TRUSTED",
            "seniority: TRUSTED",
            "hiring_manager: TRUSTED",
            "jd_text: UNTRUSTED",
        ],
    },
    "red_flags_detector": {
        "module": "trajectory.sub_agents.red_flags",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "RedFlagsReport",
        "input_sources": [
            "company_research: UNTRUSTED (derived from scrape)",
            "companies_house: TRUSTED (gov data)",
            "reviews: UNTRUSTED",
        ],
    },
    "verdict": {
        "module": "trajectory.sub_agents.verdict",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "Verdict",
        "input_sources": [
            "user_profile: TRUSTED",
            "research_bundle: UNTRUSTED (contains scraped text)",
            "retrieved_career_entries: TRUSTED",
        ],
    },
    "question_designer": {
        "module": "trajectory.sub_agents.question_designer",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "QuestionSet",
        "input_sources": [
            "verdict: TRUSTED (already validated)",
            "research_bundle: TRUSTED (already validated)",
            "user_profile: TRUSTED",
        ],
    },
    "star_polisher": {
        "module": "trajectory.sub_agents.star_polisher",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "STARPolish",
        "input_sources": [
            "raw_story: TRUSTED (user-provided in dialogue)",
            "writing_style_profile: TRUSTED",
        ],
    },
    "style_extractor": {
        "module": "trajectory.sub_agents.style_extractor",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "WritingStyleProfile",
        "input_sources": [
            "samples: UNTRUSTED (user-pasted)",
        ],
    },
    "self_audit": {
        "module": "trajectory.sub_agents.self_audit",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "SelfAuditReport",
        "input_sources": [
            "generated_output: TRUSTED (already validated)",
            "research_bundle: TRUSTED",
            "style_profile: TRUSTED",
        ],
    },
    "salary_strategist": {
        "module": "trajectory.sub_agents.salary_strategist",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "SalaryRecommendation",
        "input_sources": [
            "extracted_jd: UNTRUSTED (scraped)",
            "company_research: UNTRUSTED (scraped)",
            "salary_data: TRUSTED (gov + aggregation)",
            "user_profile: TRUSTED",
            "job_search_context: TRUSTED",
            "writing_style_profile: TRUSTED",
        ],
    },
    "intent_router": {
        "module": "trajectory.sub_agents.intent_router",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "IntentRouterOutput",
        "input_sources": [
            "user_message: UNTRUSTED",
            "recent_messages: UNTRUSTED",
            "last_session: TRUSTED",
        ],
    },
    "cv_tailor": {
        "module": "trajectory.sub_agents.cv_tailor",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "CVOutput",
        "input_sources": [
            "extracted_jd: UNTRUSTED (scraped)",
            "research_bundle: UNTRUSTED (scraped)",
            "user_profile: TRUSTED",
            "retrieved_career_entries: TRUSTED",
            "writing_style_profile: TRUSTED",
        ],
    },
    "cover_letter": {
        "module": "trajectory.sub_agents.cover_letter",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "CoverLetterOutput",
        "input_sources": [
            "extracted_jd: UNTRUSTED (scraped)",
            "research_bundle: UNTRUSTED (scraped)",
            "user_profile: TRUSTED",
            "retrieved_career_entries: TRUSTED",
            "writing_style_profile: TRUSTED",
        ],
    },
    "likely_questions": {
        "module": "trajectory.sub_agents.likely_questions",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "LikelyQuestionsOutput",
        "input_sources": [
            "extracted_jd: UNTRUSTED (scraped)",
            "research_bundle: UNTRUSTED (scraped)",
            "user_profile: TRUSTED",
            "retrieved_career_entries: TRUSTED",
        ],
    },
    "draft_reply": {
        "module": "trajectory.sub_agents.draft_reply",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "DraftReplyOutput",
        "input_sources": [
            "incoming_message: UNTRUSTED (pasted recruiter email)",
            "user_intent_hint: TRUSTED",
            "user_profile: TRUSTED",
            "writing_style_profile: TRUSTED",
            "relevant_entries: TRUSTED",
        ],
    },
    "prompt_auditor": {
        "module": "trajectory.sub_agents.prompt_auditor",
        "system_prompt_attr": "SYSTEM_PROMPT",
        "output_schema_symbol": "PromptAuditReport",
        "input_sources": [
            "audited_system_prompt: UNTRUSTED (developer-supplied)",
            "audited_output_schema: TRUSTED",
            "input_sources: TRUSTED",
        ],
    },
}


def _describe_schema(schema_symbol: str) -> str:
    """Render a Pydantic model's name + fields for the auditor's context."""
    try:
        schemas_mod = importlib.import_module("trajectory.schemas")
    except Exception:
        return schema_symbol
    model = getattr(schemas_mod, schema_symbol, None)
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        return schema_symbol
    try:
        fields = ", ".join(f"{name}: {f.annotation!s}" for name, f in model.model_fields.items())
    except Exception:
        fields = ""
    return f"{schema_symbol}({fields})" if fields else schema_symbol


async def _audit_one(agent_name: str) -> Optional[Path]:
    spec = _AGENT_REGISTRY.get(agent_name)
    if spec is None:
        logger.error("unknown agent %r. Known: %s", agent_name, sorted(_AGENT_REGISTRY))
        return None

    module = importlib.import_module(spec["module"])
    prompt = getattr(module, spec["system_prompt_attr"], None)
    if not isinstance(prompt, str):
        logger.error(
            "module %s has no string attribute %s",
            spec["module"], spec["system_prompt_attr"],
        )
        return None

    schema_description = _describe_schema(spec["output_schema_symbol"])

    logger.info("Auditing %s ...", agent_name)
    report = await prompt_auditor.audit(
        audited_agent_name=agent_name,
        audited_system_prompt=prompt,
        audited_output_schema=schema_description,
        input_sources=spec["input_sources"],
    )

    audits_dir = Path("audits")
    audits_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = audits_dir / f"{agent_name}_{ts}.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    _print_summary(report)
    return out_path


def _print_summary(report) -> None:
    highs = [w for w in report.concrete_weaknesses if w.severity == "HIGH"]
    print(
        f"[{report.overall_assessment}] {report.audited_agent_name}: "
        f"{len(report.concrete_weaknesses)} weakness(es) — {len(highs)} HIGH. "
        f"Stress test → {report.injection_stress_test.predicted_behaviour}"
    )
    for w in highs:
        print(f"  HIGH: {w.description}")


async def _audit_all() -> None:
    for name in sorted(_AGENT_REGISTRY):
        try:
            await _audit_one(name)
        except Exception as exc:
            logger.exception("audit failed for %s: %s", name, exc)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run the Prompt Auditor.")
    parser.add_argument(
        "agent", nargs="?",
        help="Agent name to audit (see --list for options).",
    )
    parser.add_argument("--all", action="store_true", help="Audit every registered agent.")
    parser.add_argument("--list", action="store_true", help="List registered agents and exit.")
    args = parser.parse_args()

    if args.list:
        for name in sorted(_AGENT_REGISTRY):
            print(name)
        return 0

    if args.all:
        asyncio.run(_audit_all())
        return 0

    if not args.agent:
        parser.print_help()
        return 2

    out = asyncio.run(_audit_one(args.agent))
    return 0 if out else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
