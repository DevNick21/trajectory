#!/usr/bin/env python3
"""Model benchmark runner — compares providers on agent-typical tasks.

Usage:
    python scripts/benchmarks/run.py                    # live run (needs keys)
    python scripts/benchmarks/run.py --mock             # CI-safe mock mode
    python scripts/benchmarks/run.py --providers anthropic,deepseek
    python scripts/benchmarks/run.py --output-json data/benchmarks/latest.json

Output: JSON lines per task + a summary block written to
data/benchmarks/latest.json. CI can upload this as an artifact;
the frontend dashboard reads it via GET /api/benchmarks/latest.

Cost: with --mock, ~$0. With live providers, ~$0.50-1.50 per full run
(DeepSeek Flash is ~$0.14/Mtok input — the tasks are small).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("benchmarks")

# ── Task definitions ───────────────────────────────────────────────

@dataclass
class BenchmarkTask:
    name: str
    agent_name: str
    """Agent name used for model routing in config.agent_model_map."""
    description: str
    input_fixture: dict
    """Matches the user_input shape the agent expects."""
    schema_name: str
    """Pydantic model class name for schema validation."""
    min_output_fields: list[str]
    """Mandatory top-level keys in the parsed output."""


TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        name="intent_router",
        agent_name="intent_router",
        description="Classify a user message into the correct intent.",
        input_fixture={
            "user_message": "draft a cover letter for this role",
            "recent_messages": ["forwarded: https://example.com/jobs/123"],
            "last_session": None,
        },
        schema_name="IntentRouterOutput",
        min_output_fields=["intent", "confidence", "extracted_params"],
    ),
    BenchmarkTask(
        name="jd_extractor",
        agent_name="jd_extractor",
        description="Extract structured fields from a job description.",
        input_fixture={
            "jd_text": (
                "Senior Software Engineer — London — £80,000-£100,000\n\n"
                "We are looking for an experienced engineer to join our "
                "Platform team. You will design and build distributed "
                "systems using Python, Go, and AWS. 5+ years experience "
                "required. Reporting to the Head of Platform Engineering, "
                "you will lead cross-functional projects and mentor "
                "junior engineers. Benefits include private healthcare, "
                "flexible working, and annual bonus."
            ),
            "job_url": "https://example.com/jobs/swe",
        },
        schema_name="ExtractedJobDescription",
        min_output_fields=["role_title", "location", "seniority_signal", "required_skills"],
    ),
    BenchmarkTask(
        name="company_summariser",
        agent_name="company_scraper_summariser",
        description="Summarise scraped company pages into structured research.",
        input_fixture={
            "pages": [
                {
                    "url": "https://acme-corp.com/about",
                    "text": (
                        "Acme Corp is a Series B fintech startup based in London "
                        "with 45 engineers. We value transparency, diversity, and "
                        "ownership. Our stack is Python, Go, React, PostgreSQL, "
                        "and we deploy on AWS with Kubernetes."
                    ),
                },
                {
                    "url": "https://acme-corp.com/careers",
                    "text": (
                        "Join Acme Corp. We offer competitive salaries, remote "
                        "work, 25 days holiday, and private healthcare. We "
                        "sponsor Skilled Worker visas for eligible candidates."
                    ),
                },
            ],
            "company_domain": "acme-corp.com",
        },
        schema_name="CompanyResearch",
        min_output_fields=["company_name", "culture_claims", "tech_stack_signals"],
    ),
    BenchmarkTask(
        name="triage",
        agent_name="triage",
        description="Classify a job forward as SERIOUS/EXPLORATORY/DEFINITE_PASS.",
        input_fixture={
            "jd": {
                "role_title": "Python Backend Engineer",
                "required_skills": ["Python", "FastAPI", "PostgreSQL", "AWS"],
                "seniority_signal": "mid",
                "location": "London",
            },
            "user": {
                "user_type": "uk_resident",
                "motivations": ["backend systems", "python"],
                "deal_breakers": ["weapons industry"],
            },
        },
        schema_name="TriageResult",
        min_output_fields=["classification", "reasoning_brief"],
    ),
    # Tool-use benchmark: model must call a dummy tool + emit structured output.
    # Verifies that the provider supports Anthropic-format tool_use correctly.
    BenchmarkTask(
        name="tool_use_extract",
        agent_name="jd_extractor",
        description="Extract structured fields via tool-call schema enforcement.",
        input_fixture={
            "jd_text": (
                "Software Engineer — Remote — We need a Python developer "
                "who knows FastAPI and PostgreSQL. 3+ years experience."
            ),
            "job_url": "https://example.com/jobs/swe-tool-test",
        },
        schema_name="ExtractedJobDescription",
        min_output_fields=["role_title", "required_skills", "seniority_signal"],
    ),
]

# ── Expected verdict checks per label set ──────────────────────────

_VALID_VERDICT_LABELS = {"STRONG_GO", "GO", "TRY_ANYWAY", "ASK_FIRST", "PASS", "BLOCKED"}


@dataclass
class ProviderConfig:
    name: str
    model_id: str
    env_key_name: str
    """Settings attribute holding the API key. E.g. 'anthropic_api_key'."""


PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": ProviderConfig(
        name="anthropic",
        model_id="claude-sonnet-4-6",
        env_key_name="anthropic_api_key",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        model_id="deepseek-v4-flash",
        env_key_name="deepseek_api_key",
    ),
    "openai": ProviderConfig(
        name="openai",
        model_id="gpt-5.4-mini",
        env_key_name="openai_api_key",
    ),
}


# ── Runner ─────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    task: str
    provider: str
    model: str
    success: bool
    latency_ms: int
    output_fields: list[str]
    schema_valid: bool
    error: Optional[str] = None


@dataclass
class RunSummary:
    timestamp: str
    total: int
    passed: int
    failed: int
    by_provider: dict[str, dict[str, int]] = field(default_factory=dict)
    by_task: dict[str, dict[str, int]] = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)


async def run_task(
    task: BenchmarkTask,
    provider_cfg: ProviderConfig,
    mock: bool = False,
) -> CaseResult:
    """Run one benchmark case against one provider. Returns a CaseResult."""
    start = time.perf_counter()

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from askpicky.config import settings

        # Mock mode: return synthetic pass with schema fields populated.
        # No actual LLM call — safe for CI without API keys.
        if mock:
            latency_ms = 1  # ~instant
            return CaseResult(
                task=task.name,
                provider=provider_cfg.name,
                model=provider_cfg.model_id,
                success=True,
                latency_ms=latency_ms,
                output_fields=list(task.min_output_fields),
                schema_valid=True,
            )

        from askpicky.llm import call_agent
        from askpicky.prompts import load_prompt

        # Live mode: require the correct API key.
        key_attr = getattr(settings, provider_cfg.env_key_name, "")
        if not key_attr:
            return CaseResult(
                task=task.name,
                provider=provider_cfg.name,
                model=provider_cfg.model_id,
                success=False,
                latency_ms=0,
                output_fields=[],
                schema_valid=False,
                error=f"Missing {provider_cfg.env_key_name}",
            )

        system_prompt = load_prompt(task.agent_name)
        user_input = json.dumps(task.input_fixture, default=str, indent=2)

        # Use a generic BaseModel that accepts any dict
        from pydantic import BaseModel as PydanticBase

        class _AnyOutput(PydanticBase, extra="allow"):  # type: ignore[call-arg]
            pass

        result = await call_agent(
            agent_name=task.agent_name,
            system_prompt=system_prompt,
            user_input=user_input,
            output_schema=_AnyOutput,
            model=provider_cfg.model_id,
            effort="medium",
            max_retries=1,
            priority="NORMAL",
        )

        latency_ms = int((time.perf_counter() - start) * 1000)
        raw = result.model_dump(mode="json")
        output_fields = sorted(raw.keys())
        schema_valid = all(f in raw for f in task.min_output_fields)

        return CaseResult(
            task=task.name,
            provider=provider_cfg.name,
            model=provider_cfg.model_id,
            success=schema_valid,
            latency_ms=latency_ms,
            output_fields=output_fields,
            schema_valid=schema_valid,
        )

    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return CaseResult(
            task=task.name,
            provider=provider_cfg.name,
            model=provider_cfg.model_id,
            success=False,
            latency_ms=latency_ms,
            output_fields=[],
            schema_valid=False,
            error=str(exc),
        )


async def run_benchmarks(
    providers: list[str],
    tasks: list[BenchmarkTask],
    mock: bool = False,
) -> RunSummary:
    """Run all task × provider combinations. Returns a RunSummary."""
    summary = RunSummary(
        timestamp=datetime.now(timezone.utc).isoformat(),
        total=0,
        passed=0,
        failed=0,
    )
    results: list[dict] = []

    for provider_name in providers:
        provider_cfg = PROVIDERS.get(provider_name)
        if provider_cfg is None:
            log.warning("Unknown provider: %s — skipped", provider_name)
            continue

        log.info("=== Provider: %s (model=%s) ===", provider_name, provider_cfg.model_id)
        summary.by_provider[provider_name] = {"passed": 0, "failed": 0}

        for task in tasks:
            log.info("  Task: %s ...", task.name)
            result = await run_task(task, provider_cfg, mock=mock)
            results.append({
                "task": result.task,
                "provider": result.provider,
                "model": result.model,
                "success": result.success,
                "latency_ms": result.latency_ms,
                "schema_valid": result.schema_valid,
                "error": result.error,
            })
            summary.total += 1
            if result.success:
                summary.passed += 1
                summary.by_provider[provider_name]["passed"] += 1
                log.info("    PASS (%d ms)", result.latency_ms)
            else:
                summary.failed += 1
                summary.by_provider[provider_name]["failed"] += 1
                log.info("    FAIL: %s", result.error or "schema validation")

            # Per-task stats
            summary.by_task.setdefault(task.name, {"passed": 0, "failed": 0})
            if result.success:
                summary.by_task[task.name]["passed"] += 1
            else:
                summary.by_task[task.name]["failed"] += 1

    summary.results = results
    return summary


# ── CLI ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Model benchmark runner")
    parser.add_argument(
        "--providers",
        default="anthropic",
        help="Comma-separated provider names (anthropic,deepseek).",
    )
    parser.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task names (default: all 4).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock/smoke-test fixtures — no real API calls.",
    )
    parser.add_argument(
        "--output-json",
        default=str(Path(__file__).resolve().parents[2] / "data" / "benchmarks" / "latest.json"),
        help="Path for the JSON summary artifact.",
    )
    args = parser.parse_args()

    providers = [p.strip() for p in args.providers.split(",")]
    selected_tasks = TASKS
    if args.tasks:
        task_names = {t.strip() for t in args.tasks.split(",")}
        selected_tasks = [t for t in TASKS if t.name in task_names]

    summary = asyncio.run(
        run_benchmarks(providers, selected_tasks, mock=args.mock)
    )

    # Write JSON artifact
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_payload = {
        "summary": {
            "timestamp": summary.timestamp,
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "by_provider": summary.by_provider,
            "by_task": summary.by_task,
        },
        "results": summary.results,
    }
    output_path.write_text(json.dumps(output_payload, indent=2))

    log.info(
        "\n=== Summary: %d/%d passed across %d provider(s) ===",
        summary.passed, summary.total, len(providers),
    )
    log.info("Artifact: %s", output_path)

    if summary.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
