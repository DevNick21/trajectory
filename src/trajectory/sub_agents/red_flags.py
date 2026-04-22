"""Phase 1 — Red Flags Detector.

Opus 4.7 xhigh LLM scan of the research bundle for non-verdict red flags
(recent layoffs, lawsuits, review patterns, Companies House distress).

System prompt verbatim from AGENTS.md §4.
"""

from __future__ import annotations

from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..schemas import (
    CompaniesHouseSnapshot,
    CompanyResearch,
    RedFlagsReport,
)
from .reviews import ReviewExcerpt


SYSTEM_PROMPT = """\
You audit a UK company's public signals for red flags that a job
candidate should know about.

You have: company research summary (values + snippets), Glassdoor review
excerpts (if available), Companies House filings history, any news
search results.

Scan for:

- Recent layoff announcements (last 12 months)
- Active lawsuits, regulatory actions, or investigations
- Glassdoor CEO approval under 40%
- Glassdoor overall rating under 3.2 with >50 reviews
- Pattern of "bait and switch" mentions in reviews
- Pay-transparency violations (reported complaints)
- Companies House: overdue filings, resolutions to wind up,
  director disqualifications

For each flag:
- Cite source (URL + verbatim snippet, or Companies House field)
- Classify severity: HARD (verdict-relevant) vs SOFT (worth mentioning)
- Explain in 1 sentence what the candidate should know

RULES:

1. Do not flag general negative reviews. A single angry review is not
   a pattern.
2. Do not flag "high turnover" unless explicit (e.g., "everyone quit
   within 6 months").
3. If no flags are found after genuine search, output `flags: []` with
   `checked: true`. Do not invent flags to appear thorough.
4. Output is strict JSON matching RedFlagsReport.
"""


def _summarise_company_research(cr: CompanyResearch) -> str:
    lines: list[str] = [f"Company: {cr.company_name}"]
    if cr.culture_claims:
        lines.append("Culture claims:")
        for c in cr.culture_claims[:20]:
            lines.append(f"- {c.claim} (url={c.url})")
    if cr.policies:
        lines.append(f"Policies: {cr.policies}")
    if cr.recent_activity_signals:
        lines.append("Recent activity: " + "; ".join(cr.recent_activity_signals[:10]))
    return "\n".join(lines)


def _summarise_companies_house(ch: Optional[CompaniesHouseSnapshot]) -> str:
    if ch is None:
        return "Companies House: not available."
    return (
        f"Companies House (company_number={ch.company_number}): "
        f"status={ch.status}, accounts_overdue={ch.accounts_overdue}, "
        f"confirmation_overdue={ch.confirmation_statement_overdue}, "
        f"no_filings_in_years={ch.no_filings_in_years}, "
        f"resolution_to_wind_up={ch.resolution_to_wind_up}"
    )


def _summarise_reviews(reviews: list[ReviewExcerpt]) -> str:
    if not reviews:
        return "Reviews: none available."
    ratings = [r.rating for r in reviews if r.rating is not None]
    avg = sum(ratings) / len(ratings) if ratings else None
    head = f"Reviews: {len(reviews)} excerpts, avg rating={avg}"
    excerpts = "\n".join(
        f"- ({r.rating or '?'}) {r.title or ''}: {r.text[:400]}" for r in reviews[:15]
    )
    return head + "\n" + excerpts


async def detect(
    company_research: CompanyResearch,
    companies_house: Optional[CompaniesHouseSnapshot] = None,
    reviews: Optional[list[ReviewExcerpt]] = None,
    session_id: Optional[str] = None,
) -> RedFlagsReport:
    # CLAUDE.md Rule 10: combined scraped content. Tier 1 only (low-stakes).
    from ..validators.content_shield import shield as shield_content

    raw_input = "\n\n".join(
        [
            _summarise_company_research(company_research),
            _summarise_companies_house(companies_house),
            _summarise_reviews(reviews or []),
        ]
    )
    user_input, _ = await shield_content(
        content=raw_input,
        source_type="scraped_company_page",
        downstream_agent="red_flags_detector",
    )

    return await call_agent(
        agent_name="phase_1_red_flags",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=RedFlagsReport,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )
