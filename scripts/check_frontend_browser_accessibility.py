"""Browser-level frontend smoke and axe accessibility gate.

Runs against the built Vite output in `apps/web/dist`. The script serves the
SPA locally, mocks `/api/*` responses inside Playwright, injects `axe-core`,
and checks the app shell plus the Assist, Memory, and Applications views.

Set ASKPICKY_REQUIRE_BROWSER_SMOKE=1 in CI/release gates to fail when Chromium
is not installed or cannot launch. Local development without browser binaries
prints a skip and exits 0.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "apps" / "web"
DIST = FRONTEND / "dist"
AXE = FRONTEND / "node_modules" / "axe-core" / "axe.min.js"
REQUIRE_BROWSER = os.getenv("ASKPICKY_REQUIRE_BROWSER_SMOKE") == "1"


def _now() -> str:
    return "2026-06-03T00:00:00Z"


def _json_response(payload: Any) -> dict[str, Any]:
    return {
        "status": 200,
        "content_type": "application/json",
        "body": json.dumps(payload),
    }


def _api_payload(path: str, query: dict[str, list[str]]) -> Any:
    if path == "/api/profile":
        return {
            "user_id": "browser-smoke-user",
            "name": "Browser Smoke",
            "user_type": "uk_resident",
            "base_location": "London",
            "salary_floor": 50000,
            "salary_target": 70000,
            "motivations": ["technical ownership"],
            "deal_breakers": ["silent data sharing"],
            "good_role_signals": ["clear engineering ownership"],
            "current_employment": "EMPLOYED",
            "search_started_date": "2026-01-01",
            "created_at": _now(),
            "updated_at": _now(),
        }
    if path == "/api/sessions":
        return {"sessions": []}
    if path == "/api/memory/inbox":
        return {
            "experience_atoms": [
                {
                    "atom_id": "atom-smoke",
                    "user_id": "browser-smoke-user",
                    "atom_type": "skill",
                    "text": "Built a dashboard that reduced manual triage time.",
                    "source_type": "manual_edit",
                    "source_id": None,
                    "source_excerpt": None,
                    "confidence": 0.8,
                    "sensitive": False,
                    "visibility": "normal",
                    "review_status": query.get("status_filter", ["pending"])[0],
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            ],
            "story_frames": [],
        }
    if path == "/api/queue":
        return []
    if path == "/api/applications":
        return {"applications": []}
    if path == "/health":
        return {"status": "ok", "service": "browser-smoke"}
    return {}


class _SpaHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        rel = unquote(parsed.path.lstrip("/"))
        candidate = (DIST / rel).resolve()
        if rel and candidate.exists() and DIST.resolve() in candidate.parents:
            return str(candidate)
        return str(DIST / "index.html")

    def log_message(self, _format: str, *_args: Any) -> None:
        return None


def _serve_dist() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SpaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def _skip(message: str) -> int:
    if REQUIRE_BROWSER:
        raise RuntimeError(message)
    print(f"browser accessibility smoke skipped: {message}")
    return 0


def _check_page(page, url: str, label: str, axe_source: str) -> list[str]:
    failures: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []

    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    def mock_api(route):
        parsed = urlparse(route.request.url)
        payload = _api_payload(parsed.path, parse_qs(parsed.query))
        route.fulfill(**_json_response(payload))

    page.route("**/api/**", mock_api)
    page.route("**/health", mock_api)
    page.goto(url, wait_until="networkidle")
    page.add_script_tag(content=axe_source)

    if page.locator("main").count() != 1:
        failures.append(f"{label}: expected exactly one main landmark")

    empty_interactive = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a, button, input, textarea, select'))
          .filter((el) => {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const id = el.getAttribute('id');
            const labelledBy = el.getAttribute('aria-labelledby');
            const hasExternalLabel =
              (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) ||
              (labelledBy && document.getElementById(labelledBy));
            const name = [
              el.getAttribute('aria-label'),
              el.getAttribute('title'),
              el.getAttribute('placeholder'),
              el.textContent,
            ].join(' ').trim();
            return !hasExternalLabel && !name;
          })
          .map((el) => el.outerHTML.slice(0, 120))
        """
    )
    if empty_interactive:
        failures.append(f"{label}: interactive controls without names: {empty_interactive[:3]}")

    axe_results = page.evaluate(
        """
        async () => await window.axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
          rules: {
            'color-contrast': { enabled: false }
          }
        })
        """
    )
    violations = axe_results.get("violations", [])
    if violations:
        formatted = [
            f"{item['id']} ({item['impact']}): {item['help']} nodes={len(item['nodes'])}"
            for item in violations[:5]
        ]
        failures.append(f"{label}: axe violations: {formatted}")

    if console_errors:
        failures.append(f"{label}: console errors: {console_errors[:5]}")
    if page_errors:
        failures.append(f"{label}: page errors: {page_errors[:5]}")

    return failures


def main() -> int:
    if not (DIST / "index.html").exists():
        return _skip("apps/web/dist is missing; run npm run --prefix apps/web build first")
    if not AXE.exists():
        return _skip("apps/web/node_modules/axe-core/axe.min.js is missing")

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return _skip(f"python playwright is unavailable: {exc}")

    axe_source = AXE.read_text(encoding="utf-8")
    server, base_url = _serve_dist()
    failures: list[str] = []
    try:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    for path, label in (
                        ("/", "dashboard shell"),
                        ("/assist", "assist"),
                        ("/memory", "memory"),
                        ("/applications", "applications"),
                    ):
                        page = browser.new_page(viewport={"width": 1280, "height": 900})
                        failures.extend(_check_page(page, base_url + path, label, axe_source))
                        page.close()
                finally:
                    browser.close()
        except PlaywrightError as exc:
            return _skip(f"chromium could not launch: {str(exc).splitlines()[0]}")
    finally:
        server.shutdown()

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("frontend browser accessibility smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
