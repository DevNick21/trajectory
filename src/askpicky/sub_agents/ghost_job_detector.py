"""Phase 1 — Ghost Job Detector.

Combines 4 signals into a `GhostJobAssessment`:

  1. STALE_POSTING          — from `extracted_jd.posted_date`
  2. NOT_ON_CAREERS_PAGE    — from `company_research.not_on_careers_page`
  3. VAGUE_JD               — from the Ghost-Job JD Scorer LLM (Opus xhigh)
  4. COMPANY_DISTRESS       — from Companies House status + filings

Combination rules (source: CLAUDE.md "Hard architectural rules" + test spec
in tests/test_ghost_job_combination.py):

  - 2+ HARD signals           -> LIKELY_GHOST, HIGH confidence
  - 1 HARD + >=1 SOFT         -> LIKELY_GHOST, MEDIUM confidence
  - 1 HARD alone              -> POSSIBLE_GHOST, MEDIUM confidence
  - 0 HARD, >=2 SOFT          -> POSSIBLE_GHOST, MEDIUM confidence
  - 0 HARD, 1 SOFT            -> POSSIBLE_GHOST, LOW confidence
  - 0 signals                 -> LIKELY_REAL, HIGH confidence

JD-scorer prompt is verbatim from AGENTS.md §5.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ..schemas import (
    Citation,
    CompaniesHouseSnapshot,
    CompanyResearch,
    ExtractedJobDescription,
    GhostJobAssessment,
    GhostJobJDScore,
    GhostSignal,
)


# ---------------------------------------------------------------------------
# Deterministic JD specificity scorer (replaces the LLM call as of 2026-05-22)
# ---------------------------------------------------------------------------
#
# The five dimensions used to need an LLM because the prompt asked for
# subjective "is this specific?" judgement. In practice the signals
# are countable:
#
#   named_hiring_manager   — boolean already supplied by jd_extractor
#   specific_tech_stack    — count of named tech tokens / branded tools
#   specific_duty_bullets  — count of bullets with action verb + object
#   specific_team_context  — regex for team-size / reporting-line language
#   specific_success_metrics — regex for numbers with units (%, $, hours, x)
#
# Each dimension scored 0.0-1.0; specificity_score is their average,
# rescaled to 0-5 to keep the downstream _vague_jd_signal thresholds
# unchanged. No LLM call — the scorer runs in ~5ms.


# Action verbs that, when starting a bullet, signal a real duty
# description rather than an aspirational tagline. Not exhaustive —
# the goal is to catch "Built / Designed / Shipped / Reduced X by Y"
# and miss "Be passionate" / "Have a positive attitude".
_ACTION_VERBS = frozenset({
    "built", "build", "designed", "design", "shipped", "ship",
    "implemented", "implement", "led", "lead", "managed", "manage",
    "owned", "own", "drove", "drive", "delivered", "deliver",
    "reduced", "reduce", "increased", "increase", "improved", "improve",
    "automated", "automate", "scaled", "scale", "migrated", "migrate",
    "refactored", "refactor", "deployed", "deploy", "integrated",
    "integrate", "developed", "develop", "architected", "architect",
    "created", "create", "wrote", "write", "tested", "test",
    "optimised", "optimised", "optimized", "optimize", "rolled",
    "launched", "launch", "negotiated", "negotiate", "established",
    "establish", "analysed", "analyzed", "analyze", "researched",
    "research", "presented", "present", "facilitated", "facilitate",
    "mentored", "mentor", "trained", "train", "coordinated",
    "coordinate", "evaluated", "evaluate", "audited", "audit",
})


# Branded tech tokens — capitalised proper nouns + acronyms that
# strongly signal real stack disclosure. Not a closed list; the
# regex below also accepts CamelCase / ALL_CAPS / X.js patterns.
_TECH_HINTS = re.compile(
    r"\b(?:"
    r"Python|JavaScript|TypeScript|Go|Rust|Java|Kotlin|Swift|C\+\+|C#|Ruby|"
    r"React|Vue|Angular|Svelte|Next\.js|Nuxt|Django|Flask|FastAPI|Rails|"
    r"Spring|Express|NestJS|GraphQL|REST|gRPC|Kafka|RabbitMQ|Redis|Postgres|"
    r"PostgreSQL|MySQL|MongoDB|DynamoDB|Snowflake|BigQuery|Databricks|"
    r"Spark|Airflow|dbt|Tableau|PowerBI|Looker|Kubernetes|Docker|Terraform|"
    r"Ansible|Pulumi|AWS|GCP|Azure|Heroku|Vercel|Netlify|Cloudflare|"
    r"Datadog|Sentry|Prometheus|Grafana|Splunk|PyTorch|TensorFlow|"
    r"scikit-learn|HuggingFace|LangChain|OpenAI|Anthropic|Claude|GPT-?\d|"
    r"FAISS|Pinecone|Weaviate|Pandas|NumPy|Jupyter|Git|GitHub|GitLab|"
    r"Linear|Jira|Notion|Figma|Slack"
    r")\b",
    re.IGNORECASE,
)


# "team of N", "X engineers", "report to the [role]", etc.
_TEAM_CONTEXT_RE = re.compile(
    r"(?i)\b(?:"
    r"team\s+of\s+\d+|"
    r"report(?:s|ing)?\s+(?:to|directly to)\s+(?:the\s+|our\s+)?[A-Z]\w+|"
    r"\d+(?:\s*-\s*\d+)?\s+(?:engineers?|developers?|designers?|analysts?|"
    r"product\s+managers?|data\s+scientists?)|"
    r"part\s+of\s+(?:a|the)\s+\d+[\s-]+person\b|"
    r"alongside\s+\d+|"
    r"working\s+with\s+(?:our|the)\s+[A-Z]\w+\s+team"
    r")\b"
)


# Numbers with units — "20%", "$1M", "3x", "40 hours/week", "p99 280ms"
_SUCCESS_METRIC_RE = re.compile(
    r"(?i)(?:"
    r"\b\d+(?:\.\d+)?\s*%|"
    r"[$£€]\s*\d+(?:\.\d+)?\s*(?:k|m|b|million|billion)?|"
    r"\b\d+(?:\.\d+)?\s*(?:x|times|fold)\b|"
    r"\b\d+\s*(?:hours?|days?|weeks?|months?|years?|sprints?)\s*(?:/|per)\s*\w+|"
    r"\bp(?:50|90|95|99|999)\s+\d+|"
    r"\b\d+(?:,\d{3})+(?:\.\d+)?\s+(?:users?|customers?|transactions?|requests?|events?|rows?|records?|queries|sessions?)\b|"
    r"\b\d+(?:k|m|b)\s+(?:users?|customers?|transactions?|requests?|rows?|records?)\b"
    r")"
)


def _score_tech_stack(jd: ExtractedJobDescription) -> tuple[float, list[str]]:
    """0.0–1.0 based on named tech tokens density."""
    text = jd.jd_text_full
    matches = set(m.group(0).lower() for m in _TECH_HINTS.finditer(text))
    # Also count well-typed tokens already extracted upstream.
    skill_count = len(jd.required_skills or [])
    total = len(matches) + skill_count
    if total >= 8:
        return 1.0, sorted(matches)[:8]
    if total >= 4:
        return 0.7, sorted(matches)
    if total >= 1:
        return 0.4, sorted(matches)
    return 0.0, []


def _score_duty_bullets(jd: ExtractedJobDescription) -> tuple[float, int]:
    """0.0–1.0 by count of bullets that start with an action verb."""
    text = jd.jd_text_full
    # Bullet candidates: lines starting with •, -, *, digit + ".", etc.
    bullet_lines = [
        ln.strip().lstrip("•-*").strip().lstrip("0123456789.").strip()
        for ln in text.splitlines()
        if ln.strip().startswith(("•", "-", "*"))
        or re.match(r"^\d+\.", ln.strip())
    ]
    action_bullets = 0
    for ln in bullet_lines:
        if not ln:
            continue
        first_word = re.split(r"[\s,;:]+", ln, maxsplit=1)[0].lower()
        if first_word in _ACTION_VERBS:
            action_bullets += 1
    if action_bullets >= 6:
        return 1.0, action_bullets
    if action_bullets >= 3:
        return 0.7, action_bullets
    if action_bullets >= 1:
        return 0.4, action_bullets
    return 0.0, action_bullets


def _score_team_context(jd: ExtractedJobDescription) -> tuple[float, list[str]]:
    matches = [m.group(0) for m in _TEAM_CONTEXT_RE.finditer(jd.jd_text_full)]
    if len(matches) >= 2:
        return 1.0, matches[:3]
    if len(matches) == 1:
        return 0.6, matches
    return 0.0, []


def _score_success_metrics(jd: ExtractedJobDescription) -> tuple[float, list[str]]:
    matches = [m.group(0) for m in _SUCCESS_METRIC_RE.finditer(jd.jd_text_full)]
    if len(matches) >= 3:
        return 1.0, matches[:5]
    if len(matches) >= 1:
        return 0.5, matches
    return 0.0, []


def _score_jd_deterministic(jd: ExtractedJobDescription) -> GhostJobJDScore:
    """5-dim specificity score using countable signals. No LLM."""
    named_score = 1.0 if jd.hiring_manager_named else 0.0
    tech_score, tech_signals = _score_tech_stack(jd)
    duty_score, duty_count = _score_duty_bullets(jd)
    team_score, team_signals = _score_team_context(jd)
    metric_score, metric_signals = _score_success_metrics(jd)

    # Rescale to 0-5 to keep downstream thresholds compatible.
    overall = (named_score + tech_score + duty_score + team_score + metric_score) * 1.0
    specificity_score = overall  # already 0-5

    specificity_signals: list[str] = []
    if jd.hiring_manager_named and jd.hiring_manager_name:
        specificity_signals.append(f"Hiring manager named: {jd.hiring_manager_name}")
    if tech_signals:
        specificity_signals.append(
            f"Specific tech stack: {', '.join(tech_signals[:5])}"
        )
    if duty_count:
        specificity_signals.append(
            f"{duty_count} action-verb duty bullet(s)"
        )
    if team_signals:
        specificity_signals.append(f"Team context: {team_signals[0]}")
    if metric_signals:
        specificity_signals.append(
            f"Success metrics cited: {', '.join(metric_signals[:3])}"
        )

    vagueness_signals: list[str] = []
    if not jd.hiring_manager_named:
        vagueness_signals.append("no hiring manager named")
    if not tech_signals:
        vagueness_signals.append("no specific tech / tooling mentioned")
    if duty_count == 0:
        vagueness_signals.append("no action-verb duty bullets")
    if not team_signals:
        vagueness_signals.append("no team-size or reporting-line context")
    if not metric_signals:
        vagueness_signals.append("no concrete success metrics")

    return GhostJobJDScore(
        named_hiring_manager=named_score,
        specific_tech_stack=tech_score,
        specific_duty_bullets=duty_score,
        specific_team_context=team_score,
        specific_success_metrics=metric_score,
        specificity_score=specificity_score,
        specificity_signals=specificity_signals,
        vagueness_signals=vagueness_signals,
    )


# ---------------------------------------------------------------------------
# Deterministic signal extraction
# ---------------------------------------------------------------------------


def _stale_signal(
    jd: ExtractedJobDescription, job_url: str
) -> Optional[GhostSignal]:
    if jd.posted_date is None:
        return None
    if not job_url:
        # No defensible citation without the JD URL.
        return None
    age_days = (date.today() - jd.posted_date).days
    if age_days < 30:
        return None
    severity = "HARD" if age_days > 60 else "SOFT"
    return GhostSignal(
        type="STALE_POSTING",
        evidence=f"Posted {age_days} days ago ({jd.posted_date.isoformat()}).",
        citation=Citation(
            kind="url_snippet",
            url=job_url,
            verbatim_snippet=f"Posted {jd.posted_date.isoformat()}",
        ),
        severity=severity,
    )


def _careers_page_signal(cr: CompanyResearch) -> Optional[GhostSignal]:
    if not cr.not_on_careers_page:
        return None
    # Need a real URL for the citation to resolve. If the scraper flagged
    # not_on_careers_page without identifying the careers page URL, the
    # signal isn't defensible — drop it rather than emit an unresolvable
    # citation.
    if not cr.careers_page_url:
        return None
    return GhostSignal(
        type="NOT_ON_CAREERS_PAGE",
        evidence=(
            "Role is not listed on the company's own careers page — a "
            "strong ghost-job signal for a real open req."
        ),
        citation=Citation(
            kind="url_snippet",
            url=cr.careers_page_url,
            verbatim_snippet="not_on_careers_page=true",
        ),
        severity="HARD",
    )


def _vague_jd_signal(
    jd: ExtractedJobDescription, score: GhostJobJDScore, job_url: str
) -> Optional[GhostSignal]:
    if score.specificity_score >= 2.5:
        return None
    if not job_url:
        return None
    severity = "HARD" if score.specificity_score < 1.5 else "SOFT"
    return GhostSignal(
        type="VAGUE_JD",
        evidence=(
            f"JD specificity score {score.specificity_score:.1f}/5. "
            f"Vagueness: {'; '.join(score.vagueness_signals[:5]) or 'no concrete specifics'}"
        ),
        citation=Citation(
            kind="url_snippet",
            url=job_url,
            verbatim_snippet=(score.vagueness_signals[:1] or [jd.role_title])[0],
        ),
        severity=severity,
    )


def _distress_signal(
    ch: Optional[CompaniesHouseSnapshot],
) -> Optional[GhostSignal]:
    if ch is None:
        return None
    if ch.status in {"DISSOLVED", "IN_ADMINISTRATION", "IN_LIQUIDATION"}:
        return GhostSignal(
            type="COMPANY_DISTRESS",
            evidence=f"Companies House status: {ch.status}.",
            citation=Citation(
                kind="gov_data",
                data_field="companies_house.status",
                data_value=ch.status,
            ),
            severity="HARD",
        )
    if ch.accounts_overdue or ch.no_filings_in_years >= 2 or ch.resolution_to_wind_up:
        detail_bits = []
        if ch.accounts_overdue:
            detail_bits.append("accounts overdue")
        if ch.no_filings_in_years >= 2:
            detail_bits.append(f"no filings in {ch.no_filings_in_years} years")
        if ch.resolution_to_wind_up:
            detail_bits.append("resolution to wind up filed")
        return GhostSignal(
            type="COMPANY_DISTRESS",
            evidence="Companies House distress signals: " + ", ".join(detail_bits),
            citation=Citation(
                kind="gov_data",
                data_field="companies_house.accounts_overdue",
                data_value=str(ch.accounts_overdue).lower(),
            ),
            severity="SOFT",
        )
    return None


# ---------------------------------------------------------------------------
# Combination
# ---------------------------------------------------------------------------


def _combine(signals: list[GhostSignal]) -> tuple[str, str]:
    hard = sum(1 for s in signals if s.severity == "HARD")
    soft = sum(1 for s in signals if s.severity == "SOFT")

    if hard >= 2:
        return "LIKELY_GHOST", "HIGH"
    if hard == 1 and soft >= 1:
        return "LIKELY_GHOST", "MEDIUM"
    if hard == 1:
        return "POSSIBLE_GHOST", "MEDIUM"
    if soft >= 2:
        return "POSSIBLE_GHOST", "MEDIUM"
    if soft == 1:
        return "POSSIBLE_GHOST", "LOW"
    return "LIKELY_REAL", "HIGH"


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


async def score(
    jd: ExtractedJobDescription,
    company_research: CompanyResearch,
    companies_house: Optional[CompaniesHouseSnapshot] = None,
    job_url: str = "",
    session_id: Optional[str] = None,
) -> GhostJobAssessment:
    # 5-dim score is now deterministic — see _score_jd_deterministic.
    # Runs in ~5ms with no LLM cost. Replaces the previous
    # phase_1_ghost_job_jd_scorer Opus/Sonnet call (2026-05-22).
    jd_score = _score_jd_deterministic(jd)

    signals: list[GhostSignal] = []
    for s in (
        _stale_signal(jd, job_url),
        _careers_page_signal(company_research),
        _vague_jd_signal(jd, jd_score, job_url),
        _distress_signal(companies_house),
    ):
        if s is not None:
            signals.append(s)

    probability, confidence = _combine(signals)

    age_days = (
        (date.today() - jd.posted_date).days if jd.posted_date else None
    )

    return GhostJobAssessment(
        probability=probability,
        signals=signals,
        confidence=confidence,
        raw_jd_score=jd_score,
        age_days=age_days,
    )
