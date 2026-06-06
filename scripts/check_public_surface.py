#!/usr/bin/env python3
"""Lightweight public-surface guardrails for development.

This is a current-tree scan, not a history audit. It protects the local
development repo from accidental reintroduction of hidden strategy docs,
runtime-agent folders, and hosted implementation references in public packages.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PUBLIC_PACKAGE_DIRS = [
    ROOT / "packages" / "core" / "src",
    ROOT / "packages" / "parsers" / "src",
    ROOT / "packages" / "evaluators" / "src",
    ROOT / "packages" / "privacy" / "src",
    ROOT / "packages" / "ai" / "src",
]

HIDDEN_PATH_PATTERNS = [
    re.compile(r"(^|/)\.claude(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)\.agents(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)\.github(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)open_core_strategy\.md$", re.IGNORECASE),
    re.compile(r"(^|/)working_pipeline\.md$", re.IGNORECASE),
]

HIDDEN_DOC_REFERENCES = [
    re.compile(r"docs[/\\]OPEN_CORE_STRATEGY\.md", re.IGNORECASE),
    re.compile(r"docs[/\\]WORKING_PIPELINE\.md", re.IGNORECASE),
    re.compile(r"\bOPEN_CORE_STRATEGY\.md\b", re.IGNORECASE),
    re.compile(r"\bWORKING_PIPELINE\.md\b", re.IGNORECASE),
]

FORBIDDEN_PUBLIC_IMPORTS = [
    re.compile(r"^\s*from\s+askpicky(?:\.|\s+import)\b"),
    re.compile(r"^\s*import\s+askpicky(?:\.|\s|$)"),
]

FORBIDDEN_PUBLIC_TERMS = [
    re.compile(r"\bcloud[/\\]billing\b", re.IGNORECASE),
    re.compile(r"\bcloud[/\\]email-inbound\b", re.IGNORECASE),
    re.compile(r"\bcloud[/\\]model-router\b", re.IGNORECASE),
    re.compile(r"\bsupabase\b", re.IGNORECASE),
    re.compile(r"\bgmail[/\\]outlook\b", re.IGNORECASE),
]

TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
    ".yaml",
}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def check() -> list[str]:
    failures: list[str] = []
    tracked = _tracked_files()

    for rel in tracked:
        for pattern in HIDDEN_PATH_PATTERNS:
            if pattern.search(rel):
                failures.append(f"hidden path is tracked: {rel}")

    for rel in tracked:
        path = ROOT / rel
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _read(path)
        for pattern in HIDDEN_DOC_REFERENCES:
            if pattern.search(text):
                failures.append(f"hidden strategy doc reference in {rel}")
                break

    for package_dir in PUBLIC_PACKAGE_DIRS:
        for path in package_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            text = _read(path)
            for line_no, line in enumerate(text.splitlines(), start=1):
                for pattern in FORBIDDEN_PUBLIC_IMPORTS:
                    if pattern.search(line):
                        failures.append(f"engine import in public package: {rel}:{line_no}")
            for pattern in FORBIDDEN_PUBLIC_TERMS:
                if pattern.search(text):
                    failures.append(f"hosted implementation term in public package: {rel}")
                    break

    return failures


def main() -> int:
    failures = check()
    if failures:
        print("Public surface check failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1
    print("Public surface check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
