"""Anthropic server-side tool definitions (PROCESS Entry 43, Workstreams C/D).

Centralised dictionary of the server-side tool dicts agents pass into
`call_with_tools(server_tools=[...])`. Tool type literals are versioned
on the platform — keeping them in one module lets the next SDK bump
update one constant rather than 6 sub-agent files.

Usage:

    from .server_tools import WEB_SEARCH, CODE_EXECUTION, WEB_FETCH

    await call_with_tools(
        agent_name="red_flags_detector",
        ...,
        server_tools=[WEB_SEARCH],
    )

The actual tool versions are pulled from
https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
and may need a refresh when Anthropic ships a new revision.
"""

from __future__ import annotations

# Web search — augment with current real-world data.
WEB_SEARCH: dict = {
    "type": "web_search_20260209",
    "name": "web_search",
}

# Web fetch — retrieve full content from specified URLs (incl. PDFs).
WEB_FETCH: dict = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
}

# Code execution — sandboxed Python for math, parsing, simulation.
CODE_EXECUTION: dict = {
    "type": "code_execution_20260209",
    "name": "code_execution",
}


# Agents that consume these constants today (post-migration):
#   verdict_deep_research    -> [WEB_SEARCH, WEB_FETCH]
#   prompt_auditor_empirical -> [CODE_EXECUTION]
#
# Future call sites: red_flags_detector (Web Search live news),
# salary_strategist + verdict (Code Execution for numerical reasoning),
# jd_extractor non-JS path (Web Fetch). Each gets its own
# `call_with_tools(server_tools=[...])` call site when migrated.
