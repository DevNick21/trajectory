"""Cross-application Memory tool layer (PROCESS Entry 43, Workstream E).

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
  - recall(query, kind, limit) — for agent-side `tool_use` invocation

Adapter: `llm.call_with_tools` agents register the Memory tool when they
want recall capability. salary_strategist, draft_reply, likely_questions
all use it post-migration.

NOTE: this module is a Workstream E scaffold. The concrete
client.beta.memory.* (or whatever the released SDK shape is) call sites
land in a follow-up session once the API surface is verified.
"""

from .recorder import (
    record_application_outcome,
    record_recruiter_interaction,
    record_negotiation_result,
)
from .recall import recall, MEMORY_TOOL_DEFINITION

__all__ = [
    "record_application_outcome",
    "record_recruiter_interaction",
    "record_negotiation_result",
    "recall",
    "MEMORY_TOOL_DEFINITION",
]
