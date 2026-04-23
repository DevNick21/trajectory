"""Managed Agents integration.

Genuine `client.beta.sessions.*` usage — sibling module to `sub_agents/`
rather than nested inside it because MA sessions are not single-turn
structured-output calls and don't fit that folder's conventions.

Only one consumer today: the company investigator, gated by
`settings.enable_managed_company_investigator`. Off by default.
"""
