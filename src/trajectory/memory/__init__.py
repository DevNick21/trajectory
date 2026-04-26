"""Cross-application Memory layer (PROCESS Entry 43, Workstream E).

This package is the cross-conversation learning loop. FAISS in `storage.py`
keeps doing static-career-history retrieval (it's the right primitive for
that); this module records and recalls events that happened ACROSS
applications — what salary the user was offered, accepted, or rejected;
what tone worked when replying to a recruiter; what interview questions
came up on a successful loop.

Public surface:
  - record_application_outcome(...)
  - record_recruiter_interaction(...)
  - record_negotiation_result(...)
  - recall(query, kind, limit) — direct pre-fetch from agent code
  - recall_as_text(...) — short prose digest for embedding in prompts

Storage: SQLite `cross_app_memory` table (auto-created on first write).
Read paths: `salary_strategist.generate` and `draft_reply.generate`
pre-fetch via `recall()` and inject results into their prompts.
"""

from .recorder import (
    record_application_outcome,
    record_recruiter_interaction,
    record_negotiation_result,
)
from .recall import recall, recall_as_text

__all__ = [
    "record_application_outcome",
    "record_recruiter_interaction",
    "record_negotiation_result",
    "recall",
    "recall_as_text",
]
