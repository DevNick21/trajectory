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


def main() -> None:
    _set_event_loop_policy()
    # Lazy import — uvicorn pulls in asyncio internals; we want our
    # policy set first.
    import uvicorn

    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(
        "trajectory.api.app:app",
        host="127.0.0.1",
        port=port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
