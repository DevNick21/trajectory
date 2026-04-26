"""Launch the FastAPI dev server with the Windows asyncio fix in place.

uvicorn's CLI calls `asyncio.run()` before importing the application
module, so any policy change inside `trajectory.api.app` happens after
the event loop has already been created. On Windows that means
Playwright's `subprocess_exec` calls raise `NotImplementedError`
because the default loop is `SelectorEventLoop`.

This wrapper sets `WindowsProactorEventLoopPolicy` before importing
uvicorn, so the loop uvicorn creates supports subprocess transports.
On non-Windows platforms it's a no-op pass-through to uvicorn.

Usage:
    python scripts/run_api.py             # defaults: 127.0.0.1:8000, reload on
"""

from __future__ import annotations

import asyncio
import os
import sys


def _set_event_loop_policy() -> None:
    if sys.platform != "win32":
        return
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as exc:  # pragma: no cover
        print(f"[run_api] could not set ProactorEventLoopPolicy: {exc}",
              file=sys.stderr)


def _patch_uvicorn_asyncio_setup() -> None:
    """Belt-and-braces: even with `loop="none"` in uvicorn.run(),
    a forked --reload child can pick up a different config path and
    re-import uvicorn.loops.asyncio. Replace its `asyncio_setup` with
    our Proactor-preserving version so even if it IS called, it does
    the right thing.
    """
    if sys.platform != "win32":
        return
    try:
        from uvicorn.loops import asyncio as _ucloop_asyncio

        def _proactor_setup(use_subprocess: bool = False) -> None:  # noqa: D401
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        _ucloop_asyncio.asyncio_setup = _proactor_setup
    except Exception as exc:  # pragma: no cover
        print(f"[run_api] could not patch uvicorn asyncio_setup: {exc}",
              file=sys.stderr)


def main() -> None:
    _set_event_loop_policy()
    # Lazy import — uvicorn pulls in asyncio internals; we want our
    # policy set first.
    import uvicorn  # noqa: F401  (imported by patcher below)
    _patch_uvicorn_asyncio_setup()

    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(
        "trajectory.api.app:app",
        host="127.0.0.1",
        port=port,
        reload=True,
        log_level="info",
        # CRITICAL on Windows: uvicorn's default `loop="auto"` calls
        # asyncio_setup() which OVERWRITES our ProactorEventLoopPolicy
        # with SelectorEventLoopPolicy (uvicorn/loops/asyncio.py),
        # killing Playwright's subprocess_exec. `loop="none"` skips
        # uvicorn's setup entirely so the policy we set above survives
        # all the way to the actual event loop creation.
        loop="none",
    )


if __name__ == "__main__":
    main()
