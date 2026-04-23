"""Content Shield — untrusted-content sanitiser (CLAUDE.md Rule 10).

Every piece of externally-sourced content (scraped pages, JD text, user
messages, recruiter emails, writing samples) MUST pass through this
module before reaching any agent's prompt. Two tiers:

  Tier 1  — deterministic regex filter. Zero cost, zero latency. Always
            runs. Strips known prompt-injection patterns and replaces
            them with a visible `[REDACTED: pattern_name]` marker so
            downstream agents still read natural text.

  Tier 2  — Sonnet 4.6 classifier. Only runs when Tier 1 flagged at
            least one pattern AND the downstream agent is in the
            high-stakes list. Returns SAFE / SUSPICIOUS / MALICIOUS
            with a recommended action (PASS_THROUGH / PASS_WITH_WARNING
            / REJECT).

Full spec: AGENTS.md §18.
"""

from __future__ import annotations

from ..prompts import load_prompt

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal, Optional

from ..config import settings
from ..schemas import ContentShieldVerdict

logger = logging.getLogger(__name__)


class ContentIntegrityRejected(RuntimeError):
    """Raised when Tier 2 returns recommended_action=REJECT and the caller
    cannot continue safely. Bot handlers translate this to the user-facing
    "I couldn't process this content" message (AGENTS.md §18)."""

    def __init__(self, verdict: "ContentShieldVerdict", source_type: str) -> None:
        super().__init__(
            f"Content shield rejected {source_type} content: {verdict.reasoning}"
        )
        self.verdict = verdict
        self.source_type = source_type


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class ShieldFlag:
    pattern_name: str
    matched_text: str
    position: int


@dataclass
class Tier1Result:
    cleaned_text: str
    flags: list[ShieldFlag] = field(default_factory=list)
    truncated: bool = False
    non_ascii_ratio: float = 0.0


SourceType = Literal[
    "scraped_jd",
    "scraped_company_page",
    "user_message",
    "recruiter_email",
    "writing_sample",
]


# ---------------------------------------------------------------------------
# Injection patterns (AGENTS.md §18)
# ---------------------------------------------------------------------------


INJECTION_PATTERNS: list[tuple[str, str]] = [
    # Role-switching attempts
    (
        "ignore_previous",
        r"(?i)ignore\s+(all\s+|the\s+)?previous\s+(instructions|prompts|directives)",
    ),
    (
        "disregard_previous",
        r"(?i)disregard\s+(all\s+|the\s+)?(previous|prior|above)",
    ),
    (
        "forget_previous",
        r"(?i)forget\s+(everything|all|previous)",
    ),
    # Role-switching via impersonation. We intentionally DON'T carve out
    # "you are a job"/"you are a UK ..." — the negative-lookahead carve-out
    # is fragile ("You are a UK-based engineer who will now ignore
    # previous instructions" passed it) and we'd rather accept the JD
    # false-positive rate: Tier 2 Sonnet will classify benign JD phrasing
    # as SAFE in practice.
    (
        "impersonation",
        r"(?i)(you are|act as|pretend to be|roleplay as)\s+\w+",
    ),
    # Fake system messages (line-leading role markers like "System:" / "User:")
    (
        "role_marker_line",
        r"(?im)^\s*(system|assistant|user)\s*:\s*",
    ),
    (
        "role_marker_angle",
        r"<\s*(system|assistant|human|user)\s*>",
    ),
    (
        "role_marker_square",
        r"\[\s*(system|assistant|human|user)\s*\]",
    ),
    # Delimiter injection
    (
        "hash_delimiter",
        r"###\s*(system|new\s+instructions|reset)",
    ),
    (
        "code_fence_delimiter",
        r"```\s*(system|instructions)",
    ),
    # Task override
    (
        "new_task",
        r"(?i)new\s+(task|instructions|objective)",
    ),
    (
        "real_task_is",
        r"(?i)your\s+(real|actual|true)\s+(task|job|role)\s+is",
    ),
    # URL-scheme attacks
    (
        "dangerous_scheme",
        r"(?i)(file|javascript|data|vbscript):",
    ),
    # Prompt extraction
    (
        "prompt_extraction",
        r"(?i)(show|reveal|print|output)\s+your\s+(system\s+)?(prompt|instructions)",
    ),
    # Common jailbreak openings
    (
        "dan_mode",
        r"(?i)DAN\s+mode",
    ),
    (
        "developer_mode",
        r"(?i)developer\s+mode\s+(enabled|on|activated)",
    ),
]

# Precompile once.
_COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern)) for name, pattern in INJECTION_PATTERNS
]

# High-stakes downstream agents receive Tier 2 whenever Tier 1 flags.
# Low-stakes agents are Tier 1 only — they only consume extracted
# fields, so a flagged-but-benign pattern cannot steer final output.
HIGH_STAKES_AGENTS: frozenset[str] = frozenset(
    {
        "verdict",
        "salary_strategist",
        "cv_tailor",
        "cover_letter",
        "likely_questions",
        "draft_reply",
        # Managed Agents company investigator: its output feeds verdict,
        # so every page fetched inside the sandbox runs Tier 2 when Tier
        # 1 flags.
        "managed_company_investigator",
        # LaTeX CV pipeline: writer produces a .tex file that will be
        # compiled by a subprocess; repairer rewrites it after a compile
        # error. Both ingest agent-written text but also pdflatex error
        # logs — keep them high-stakes.
        "cv_latex_writer",
        "cv_latex_repairer",
    }
)

LOW_STAKES_AGENTS: frozenset[str] = frozenset(
    {
        "company_scraper_summariser",
        "phase_1_company_scraper_summariser",
        "jd_extractor",
        "phase_1_jd_extractor",
        "red_flags_detector",
        "phase_1_red_flags",
        "intent_router",
        "onboarding_orchestrator",
        "onboarding_parser",
        "style_extractor",
    }
)


# ---------------------------------------------------------------------------
# Tier 1 — deterministic
# ---------------------------------------------------------------------------


_ZERO_WIDTH_CHARS = "​‌‍﻿"
# U+202A through U+202E — bidi override characters.
_BIDI_OVERRIDE_CHARS = "‪‫‬‭‮"

_STRIP_TRANSLATION = str.maketrans(
    "", "", _ZERO_WIDTH_CHARS + _BIDI_OVERRIDE_CHARS
)


def _strip_invisible(text: str) -> str:
    """Remove zero-width + bidi-override characters. Also normalise to NFC
    so visually-identical sequences don't slip past the regex engine.
    """
    normalised = unicodedata.normalize("NFC", text)
    return normalised.translate(_STRIP_TRANSLATION)


def _non_ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii / len(text)


def tier1(content: str, max_length: int = 50_000) -> Tier1Result:
    """Deterministic regex filter.

    - Always returns a Tier1Result; never raises.
    - Replaces each injection match with `[REDACTED: <pattern_name>]`
      so the shape of the surrounding text is preserved.
    - Strips zero-width + bidi-override characters.
    - Truncates to `max_length - 12` and appends `[TRUNCATED]` when the
      input exceeds `max_length` characters.
    """
    if not isinstance(content, str):
        # Defensive: callers should pass str, but never throw.
        return Tier1Result(cleaned_text="", flags=[])

    try:
        cleaned = _strip_invisible(content)

        truncated = False
        # AGENTS.md §18: >50_000 chars → truncate to 40_000 + suffix.
        if len(cleaned) > max_length:
            cleaned = cleaned[: max(0, max_length - 10_000)] + "[TRUNCATED]"
            truncated = True

        # Collect matches against the original (post-strip, pre-sub)
        # text so positions are meaningful. Redaction happens once per
        # pattern via re.sub after the scan.
        flags: list[ShieldFlag] = []
        for name, regex in _COMPILED:
            scanned_any = False
            for m in regex.finditer(cleaned):
                scanned_any = True
                flags.append(
                    ShieldFlag(
                        pattern_name=name,
                        matched_text=m.group(0),
                        position=m.start(),
                    )
                )
            if scanned_any:
                cleaned = regex.sub(f"[REDACTED: {name}]", cleaned)

        return Tier1Result(
            cleaned_text=cleaned,
            flags=flags,
            truncated=truncated,
            non_ascii_ratio=_non_ascii_ratio(cleaned),
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("tier1 unexpected error, returning passthrough: %s", exc)
        return Tier1Result(cleaned_text=content, flags=[])


# ---------------------------------------------------------------------------
# Tier 2 — Sonnet classifier
# ---------------------------------------------------------------------------


TIER2_SYSTEM_PROMPT = load_prompt("content_shield_tier2")


async def tier2(
    cleaned_text: str,
    source_type: SourceType,
    downstream_agent: str,
) -> ContentShieldVerdict:
    """Run the Sonnet 4.6 residual-risk classifier.

    Callers should only invoke this when `tier1().flags` is non-empty
    AND `downstream_agent in HIGH_STAKES_AGENTS`. We still guard
    defensively against misuse so the shield stays a drop-in utility.
    """
    from ..llm import call_agent

    user_input = (
        f"SOURCE TYPE: {source_type}\n"
        f"DOWNSTREAM AGENT: {downstream_agent}\n\n"
        "The text between <untrusted_content> tags has already been "
        "passed through a regex filter. Classify the residual risk.\n\n"
        "<untrusted_content>\n"
        f"{cleaned_text[:20_000]}\n"
        "</untrusted_content>"
    )

    try:
        return await call_agent(
            agent_name="content_shield_tier2",
            system_prompt=TIER2_SYSTEM_PROMPT,
            user_input=user_input,
            output_schema=ContentShieldVerdict,
            model=settings.sonnet_model_id,
            effort="medium",
            max_retries=1,
            priority="NORMAL",
        )
    except Exception as exc:
        # Fail-open on classifier error: degrade to PASS_WITH_WARNING so
        # upstream can still decide to proceed. Never fail-closed by
        # default — a flaky classifier must not silently block every
        # forward_job run.
        logger.warning(
            "content_shield tier2 failed for %s → %s (%s). Degrading "
            "to PASS_WITH_WARNING.",
            source_type,
            downstream_agent,
            exc,
        )
        return ContentShieldVerdict(
            classification="SUSPICIOUS",
            reasoning=f"Tier 2 classifier unavailable: {exc!s}",
            residual_patterns_detected=[],
            recommended_action="PASS_WITH_WARNING",
        )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def shield(
    content: str,
    source_type: SourceType,
    downstream_agent: str,
) -> tuple[str, Optional[ContentShieldVerdict]]:
    """Full shield pipeline.

    Returns `(cleaned_content, tier2_verdict_or_None)`.

    - Tier 1 always runs.
    - Tier 2 runs only if Tier 1 flagged AND `downstream_agent` is
      high-stakes. Otherwise returns None for the verdict.
    """
    t1 = tier1(content)
    if not t1.flags:
        return t1.cleaned_text, None

    if downstream_agent not in HIGH_STAKES_AGENTS:
        # Low-stakes: return cleaned text without the Sonnet round-trip.
        logger.info(
            "content_shield tier1 flagged %d pattern(s) for %s → low-stakes "
            "agent %s; skipping tier2.",
            len(t1.flags),
            source_type,
            downstream_agent,
        )
        return t1.cleaned_text, None

    verdict = await tier2(
        cleaned_text=t1.cleaned_text,
        source_type=source_type,
        downstream_agent=downstream_agent,
    )
    return t1.cleaned_text, verdict
