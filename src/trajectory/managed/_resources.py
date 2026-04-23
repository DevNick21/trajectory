"""Shared Managed Agents agent + environment for Trajectory.

Both are created once per deployment, cached by ID in
`data/managed_agents.json`, and reused across invocations. When the
system prompt or tool list changes, bump the version sentinel in
`_AGENT_SPEC` — that forces a new `client.beta.agents.create(...)` call
which produces a fresh `(agent_id, version)`. Existing archived
sessions keep referencing their original version cleanly; Managed
Agents resources are versioned, not mutated in place.

Cache shape:
    {
      "agent": {"id": "agt_...", "version": <int>, "spec_hash": "<hash>"},
      "environment": {"id": "env_..."}
    }

`spec_hash` is a fingerprint of the system prompt + tool list in this
module. When the fingerprint changes, we recreate the agent so
downstream sessions see the new prompt. Environment is not
fingerprinted — it only changes when networking/config changes, which
is rare enough to justify a manual cache wipe.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ..config import settings
from ..prompts import load_prompt

logger = logging.getLogger(__name__)


_CACHE_PATH = Path("data") / "managed_agents.json"

_AGENT_NAME = "trajectory-company-investigator"
_ENVIRONMENT_NAME = "trajectory-investigator-env"
_AGENT_MODEL = settings.opus_model_id

# Full agent toolset — includes web_fetch, web_search, bash, file ops.
# The system prompt scopes this down to "web tools only".
_AGENT_TOOLS: list[dict[str, Any]] = [{"type": "agent_toolset_20260401"}]

_ENVIRONMENT_CONFIG: dict[str, Any] = {
    "type": "cloud",
    "networking": {"type": "unrestricted"},  # needed for arbitrary company domains
}


def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        logger.warning("corrupt %s: %r — recreating", _CACHE_PATH, exc)
        return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _spec_hash() -> str:
    """Fingerprint of the inputs that define the agent's behaviour.

    When system prompt or tool list change, the hash changes and the
    agent is recreated rather than silently referenced with stale
    behaviour.
    """
    system_prompt = load_prompt("managed_company_investigator")
    payload = json.dumps(
        {"system": system_prompt, "tools": _AGENT_TOOLS, "model": _AGENT_MODEL},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


async def get_or_create_agent(client: Any) -> tuple[str, int]:
    """Return (agent_id, version), creating + caching on first call.

    On 404 from Managed Agents (out-of-band deletion in the dev
    console), the cache is invalidated and the agent is recreated.
    """
    cache = _load_cache()
    current_hash = _spec_hash()
    cached_agent = cache.get("agent") or {}

    if (
        cached_agent.get("id")
        and cached_agent.get("spec_hash") == current_hash
    ):
        return cached_agent["id"], int(cached_agent.get("version", 1))

    if cached_agent.get("id") and cached_agent.get("spec_hash") != current_hash:
        logger.info(
            "MA agent spec changed (%s → %s); creating a new agent version",
            cached_agent.get("spec_hash"),
            current_hash,
        )

    system_prompt = load_prompt("managed_company_investigator")
    agent = await client.beta.agents.create(
        name=_AGENT_NAME,
        model=_AGENT_MODEL,
        system=system_prompt,
        tools=_AGENT_TOOLS,
    )
    agent_id = getattr(agent, "id")
    version = int(getattr(agent, "version", 1) or 1)

    cache["agent"] = {
        "id": agent_id,
        "version": version,
        "spec_hash": current_hash,
    }
    _save_cache(cache)
    logger.info("created MA agent %s (version %d)", agent_id, version)
    return agent_id, version


async def get_or_create_environment(client: Any) -> str:
    """Return cached environment ID, creating + caching on first call."""
    cache = _load_cache()
    cached_env = cache.get("environment") or {}
    if cached_env.get("id"):
        return cached_env["id"]

    env = await client.beta.environments.create(
        name=_ENVIRONMENT_NAME,
        config=_ENVIRONMENT_CONFIG,
    )
    env_id = getattr(env, "id")
    cache["environment"] = {"id": env_id}
    _save_cache(cache)
    logger.info("created MA environment %s", env_id)
    return env_id


def invalidate_cache(*, agent: bool = False, environment: bool = False) -> None:
    """Drop cached IDs. Called on 404 or manual admin action."""
    cache = _load_cache()
    if agent:
        cache.pop("agent", None)
    if environment:
        cache.pop("environment", None)
    _save_cache(cache)


def _resolve_cache_path() -> Path:
    """Exposed for tests — lets them redirect the cache to a tempdir."""
    return _CACHE_PATH


def _set_cache_path_for_tests(path: Path) -> None:
    """Tests may override the cache path; production code must not."""
    global _CACHE_PATH
    _CACHE_PATH = path
