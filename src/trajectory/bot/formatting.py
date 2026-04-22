"""Render structured outputs as Telegram HTML messages.

Telegram caps messages at 4096 characters. All formatters return list[str]
where each element is a separate message. Use HTML parse_mode.
"""

from __future__ import annotations

from ..schemas import (
    Citation,
    CoverLetterOutput,
    CVOutput,
    LikelyQuestionsOutput,
    SalaryRecommendation,
    Verdict,
)

_TG_LIMIT = 4096


def _split(text: str) -> list[str]:
    if len(text) <= _TG_LIMIT:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:_TG_LIMIT])
        text = text[_TG_LIMIT:]
    return chunks


def _esc(s: str) -> str:
    """Minimal HTML escaping for user-generated content."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def format_citation(c: Citation) -> str:
    if c.kind == "url_snippet":
        url = _esc(c.url or "")
        snippet = _esc((c.verbatim_snippet or "")[:120])
        return f'<a href="{url}">source</a>: <i>"{snippet}"</i>'
    if c.kind == "gov_data":
        return f"<code>{_esc(c.data_field or '')} = {_esc(c.data_value or '')}</code>"
    if c.kind == "career_entry":
        return f"<code>career:{_esc(c.entry_id or '')}</code>"
    return ""


# ---------------------------------------------------------------------------
# Phase 1 progress
# ---------------------------------------------------------------------------

_PHASE1_LABELS = {
    "phase_1_jd_extractor": "JD extraction",
    "phase_1_company_scraper_summariser": "Company research",
    "companies_house": "Companies House",
    "reviews": "Reviews",
    "phase_1_ghost_job_jd_scorer": "Ghost-job check",
    "salary_data": "Salary data",
    "sponsor_register": "Sponsor Register",
    "soc_check": "SOC threshold",
    "phase_1_red_flags": "Red flags",
}


def format_phase1_progress(
    completed_agents: list[str],
    all_agents: list[str],
) -> str:
    lines = ["<b>Running checks…</b>"]
    for a in all_agents:
        label = _PHASE1_LABELS.get(a, a)
        tick = "✓" if a in completed_agents else "○"
        lines.append(f"{tick} {_esc(label)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def format_verdict(v: Verdict) -> list[str]:
    emoji = "✅" if v.decision == "GO" else "🚫"
    lines = [
        f"{emoji} <b>{_esc(v.headline)}</b>",
        f"Confidence: {v.confidence_pct}%",
        "",
    ]

    if v.hard_blockers:
        lines.append("⛔ <b>Hard blockers</b>")
        for b in v.hard_blockers:
            lines.append(f"• <b>{_esc(b.type)}</b> — {_esc(b.detail)}")
        lines.append("")

    if v.stretch_concerns:
        lines.append("⚠️ <b>Concerns</b>")
        for c in v.stretch_concerns:
            lines.append(f"• {_esc(c.type)}: {_esc(c.detail)}")
        lines.append("")

    lines.append("📋 <b>Reasoning</b>")
    for r in v.reasoning:
        cite = format_citation(r.citation)
        lines.append(f"• {_esc(r.claim)} — {cite}")
    lines.append("")

    mf = v.motivation_fit
    if mf.motivation_evaluations:
        lines.append("💡 <b>Motivation fit</b>")
        for ev in mf.motivation_evaluations:
            status = ev.get("status", "")
            icon = "✓" if status == "aligns" else ("✗" if status == "misaligns" else "·")
            lines.append(f"{icon} {_esc(str(ev.get('motivation', '')))}")

    return _split("\n".join(lines))


# ---------------------------------------------------------------------------
# CV
# ---------------------------------------------------------------------------


def format_cv_output(cv: CVOutput) -> list[str]:
    lines = [
        f"<b>{_esc(cv.name)}</b>",
        f"<i>{_esc(cv.professional_summary)}</i>",
        "",
        "📄 <b>CV attached as .docx and .pdf.</b>",
        "Preview:",
        "",
    ]
    for role in cv.experience[:3]:
        lines.append(f"<b>{_esc(role.title)}</b> @ {_esc(role.company)} ({_esc(role.dates)})")
        for b in role.bullets[:2]:
            lines.append(f"  • {_esc(b.text)}")
        lines.append("")
    return _split("\n".join(lines))


# ---------------------------------------------------------------------------
# Cover letter
# ---------------------------------------------------------------------------


def format_cover_letter(cl: CoverLetterOutput) -> list[str]:
    lines = [
        f"<b>Cover letter</b> → {_esc(cl.addressed_to)}",
        f"<i>{cl.word_count} words</i>",
        "",
        "📄 <b>Attached as .docx and .pdf.</b>",
        "Preview:",
        "",
    ]
    for para in cl.paragraphs:
        lines.append(_esc(para))
        lines.append("")
    return _split("\n".join(lines))


# ---------------------------------------------------------------------------
# Likely questions
# ---------------------------------------------------------------------------


def format_likely_questions(lq: LikelyQuestionsOutput) -> list[str]:
    lines = [f"<b>Likely interview questions</b> ({len(lq.questions)} total)", ""]
    for i, q in enumerate(lq.questions, 1):
        likelihood_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}.get(
            q.likelihood, "•"
        )
        lines.append(
            f"{i}. {likelihood_icon} <b>{_esc(q.question)}</b>\n"
            f"   <i>{_esc(q.bucket)}</i> — {_esc(q.strategy_note)}"
        )
        lines.append("")
    return _split("\n".join(lines))


# ---------------------------------------------------------------------------
# Salary recommendation
# ---------------------------------------------------------------------------


def format_salary_recommendation(s: SalaryRecommendation) -> list[str]:
    lines = [
        "<b>Salary strategy</b>",
        "",
        f"Opening: <b>£{s.opening_number:,}</b>",
        f"Floor:   £{s.floor:,}",
        f"Ceiling: £{s.ceiling:,}",
        f"Confidence: {s.confidence}",
    ]
    if s.sponsor_constraint_active:
        lines.append("⚠️ Sponsor threshold active — floor includes SOC going rate.")
    if s.urgency_note:
        lines.append(f"\n<i>{_esc(s.urgency_note)}</i>")
    lines.append("")

    lines.append("<b>Scripts</b>")
    script_labels = {
        "recruiter_first_call": "Recruiter first call",
        "hiring_manager_ask": "Hiring manager ask",
        "offer_stage_counter": "Offer counter",
        "pushback_response": "Pushback response",
    }
    for key, label in script_labels.items():
        if script := s.scripts.get(key):
            lines.append(f"\n<b>{label}:</b>")
            lines.append(f'<i>"{_esc(script)}"</i>')

    if s.data_gaps:
        lines.append(f"\n⚠️ Data gaps: {_esc(', '.join(s.data_gaps))}")

    return _split("\n".join(lines))
