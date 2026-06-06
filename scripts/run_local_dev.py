#!/usr/bin/env python3
"""Run the local AskPicky API and web app together.

This is a development convenience wrapper around:

  - python scripts/run_api.py
  - npm run --prefix apps/web dev

It enables local mode by default so a new checkout can run the JD-first
workflow without managed AI credentials.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "apps" / "web"


def _npm() -> str:
    return "npm.cmd" if sys.platform == "win32" else "npm"


def _spawn(name: str, args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    print(f"[local-dev] starting {name}: {' '.join(args)}", flush=True)
    return subprocess.Popen(args, cwd=str(cwd), env=env)


def _terminate(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    print(f"[local-dev] stopping {name}", flush=True)
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=8)
    except Exception:
        proc.kill()


def main() -> int:
    env = os.environ.copy()
    env.setdefault("ASKPICKY_LOCAL_MODE", "1")
    env.setdefault("DEMO_USER_ID", "local-user")
    env.setdefault("API_PORT", "8000")
    env.setdefault("API_RELOAD", "1")

    api = _spawn(
        "api",
        [sys.executable, "scripts/run_api.py"],
        cwd=ROOT,
        env=env,
    )
    web = _spawn(
        "web",
        [_npm(), "run", "dev", "--", "--host", "127.0.0.1"],
        cwd=WEB_DIR,
        env=env,
    )

    print("[local-dev] web: http://127.0.0.1:5173", flush=True)
    print("[local-dev] api: http://127.0.0.1:8000/health", flush=True)
    print("[local-dev] press Ctrl+C to stop both processes", flush=True)

    try:
        while True:
            for name, proc in (("api", api), ("web", web)):
                code = proc.poll()
                if code is not None:
                    other = web if proc is api else api
                    _terminate(other, "web" if proc is api else "api")
                    print(f"[local-dev] {name} exited with code {code}", flush=True)
                    return int(code)
            try:
                api.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        print("\n[local-dev] received interrupt", flush=True)
        return 0
    finally:
        _terminate(api, "api")
        _terminate(web, "web")


if __name__ == "__main__":
    raise SystemExit(main())
