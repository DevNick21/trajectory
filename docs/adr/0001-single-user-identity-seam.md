# ADR-0001: `get_current_user_id` as the single-user→multi-user seam

Status: accepted
Date: 2026-04-24

## Context

The FastAPI surface today runs single-user with `settings.demo_user_id`
threaded through every route. The Telegram bot uses the Telegram
numeric user id directly (which equals `demo_user_id` in the demo
deployment). Post-demo we want an auth layer that derives identity
from a session cookie / bearer token.

## Decision

`src/trajectory/api/dependencies.py::get_current_user_id` is the
ONLY place that materialises a user id on the API side. Routes
`Depends(get_current_user_id)` — they never read `settings.demo_user_id`
directly. When auth lands, only this function changes: it starts
reading the token and resolving the authenticated user. Every
downstream consumer stays untouched.

The bot side (`src/trajectory/bot/handlers.py::get_user_id`) is
analogous. Identity is derived from `update.effective_user.id`; no
other call site should inline the lookup.

## Consequences

- Removing `DEMO_USER_ID` becomes a one-file change on each surface.
- The rate limiter (`ratelimit.py`) keys on user_id, so it transparently
  becomes per-authenticated-user when auth lands.
- Tests should monkeypatch the dependency, not `settings.demo_user_id`,
  once auth replaces the env var — but today both approaches are
  functionally identical.

## What is NOT decided here

- The auth mechanism itself (OAuth, JWT, session cookie, Stripe-like
  API keys). That's a separate ADR.
- Cross-surface identity unification (should bot + web for the same
  user share a row?). Deferred — the current pattern maps both
  surfaces onto the same row via shared `user_profiles` keyed by
  `user_id`, so the seam is ready even if the policy isn't.
