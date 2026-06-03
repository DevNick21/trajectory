"""Static frontend accessibility smoke checks.

This is not a replacement for Playwright + axe. It is a cheap CI gate for
the most common regression in the current React codebase: icon-only buttons
without an accessible name. The V2 plan still requires real browser-level axe
coverage; this script keeps obvious regressions out while that tooling lands.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = ROOT / "frontend" / "src"

BUTTON_RE = re.compile(r"<button\b(?P<attrs>[^>]*)>(?P<body>.*?)</button>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
JSX_EXPR_RE = re.compile(r"\{[^{}]*\}")


def _visible_text(body: str) -> str:
    without_tags = TAG_RE.sub(" ", body)
    without_simple_exprs = JSX_EXPR_RE.sub(" ", without_tags)
    return re.sub(r"\s+", " ", without_simple_exprs).strip()


def _has_accessible_name(attrs: str, body: str) -> bool:
    if re.search(r"\baria-label\s*=", attrs):
        return True
    if re.search(r"\baria-labelledby\s*=", attrs):
        return True
    if _visible_text(body):
        return True
    # Dynamic children on the shared Button primitive are acceptable; the
    # callsite is responsible for the accessible name.
    if "{children}" in body:
        return True
    return False


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    failures: list[str] = []
    for match in BUTTON_RE.finditer(source):
        if _has_accessible_name(match.group("attrs"), match.group("body")):
            continue
        line = source.count("\n", 0, match.start()) + 1
        failures.append(f"{path.relative_to(ROOT)}:{line} button has no accessible name")
    return failures


def main() -> int:
    failures: list[str] = []
    for path in FRONTEND_SRC.rglob("*.tsx"):
        failures.extend(check_file(path))
    if failures:
        print("Frontend accessibility smoke failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("frontend accessibility smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
