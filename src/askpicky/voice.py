"""Voice personas — three structural rhetoric modes the generators
compose ON TOP of the user's WritingStyleProfile.

Layering:
  - The WritingStyleProfile contributes phonetics, vocabulary, sentence
    rhythm — the user-specific "how they sound" signals.
  - The VoicePersona contributes structural rhetoric — Thought Partner
    framing for cover letters, Value Architect framing for CV bullets,
    Direct Operator framing for follow-ups.

Both layers ship inside every Phase 4 generator's system prompt. The
persona is the outer wrapper; the style profile narrows the persona
to sound like THIS user.

Intent -> persona mapping (the orchestrator dispatches on this):

  draft_cover_letter            -> thought_partner
  cv_tailor / draft_cv          -> value_architect
  predict_questions / star      -> value_architect
  draft_reply (recruiter chase) -> direct_operator
  future: networking outreach   -> direct_operator
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

VoicePersona = Literal["thought_partner", "value_architect", "direct_operator"]


_PROMPT_DIR = Path(__file__).parent / "prompts" / "voice"


# Hard-coded fallback if a persona prompt file is missing — never
# silently drop the layering, always inject at least the headline
# instruction. Keeps generators robust to packaging glitches.
_FALLBACK = {
    "thought_partner": (
        "VOICE: Thought Partner. Write like you're explaining this to a "
        "smart peer over coffee. Acknowledge real-world chaos, doubts, "
        "and specific wins. No clichés, no buzzwords, no template "
        "phrases. Sentences mix long and short."
    ),
    "value_architect": (
        "VOICE: Value Architect. Use the Action -> Result -> Impact "
        "frame for every line. Concrete verbs, specific numbers, "
        "organizational consequences (people / money / time / risk). "
        "Never 'responsible for' or 'helped with'."
    ),
    "direct_operator": (
        "VOICE: Direct Operator. 3-5 short sentences. Hyper-specific "
        "opener (reference something they've done). One concrete CTA. "
        "Explicit easy-out. No 'I hope this finds you well'. "
        "Sign off with 'Best' + name."
    ),
}


def load_persona_prompt(persona: VoicePersona) -> str:
    """Load the persona's markdown prompt fragment from disk.

    Falls back to the hard-coded headline when the file isn't on
    disk — should only happen if the package was installed without
    the prompts/ data files.
    """
    path = _PROMPT_DIR / f"{persona}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _FALLBACK[persona]
    except Exception:
        return _FALLBACK[persona]


# Intent name -> default persona. Generators look up against this
# before falling back to their own per-call default.
_INTENT_TO_PERSONA: dict[str, VoicePersona] = {
    "draft_cover_letter": "thought_partner",
    "cover_letter": "thought_partner",
    "draft_cv": "value_architect",
    "cv_tailor": "value_architect",
    "predict_questions": "value_architect",
    "likely_questions": "value_architect",
    "star_polisher": "value_architect",
    "question_designer": "value_architect",
    "draft_reply": "direct_operator",
    # Future intents:
    "networking_outreach": "direct_operator",
    "thank_you_note": "direct_operator",
}


def persona_for_intent(intent: str) -> Optional[VoicePersona]:
    """Default persona for a routed intent. None if unmapped."""
    return _INTENT_TO_PERSONA.get(intent)


def compose_system_prompt(
    base_prompt: str,
    persona: Optional[VoicePersona],
    *,
    style_block: Optional[str] = None,
) -> str:
    """Layer persona + style + the agent's base system prompt.

    Order:
      1. Persona structural prompt (outer wrapper — "Value Architect")
      2. User's style profile block (inner — phonetics, vocabulary)
      3. The agent's task-specific instructions

    The agent's prompt stays the deepest layer so its task contract
    (Citations API rules, schema constraints, etc.) is the final
    word the model reads before generation.
    """
    parts: list[str] = []
    if persona:
        parts.append(load_persona_prompt(persona))
        parts.append("")  # blank line separator
    if style_block:
        parts.append(style_block)
        parts.append("")
    parts.append(base_prompt)
    return "\n".join(parts)
