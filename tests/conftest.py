"""Pytest configuration - add the engine source root to sys.path."""

import sys
from pathlib import Path

# Allow public packages to import without installing the monorepo.
ROOT = Path(__file__).parent.parent
for package in ("engine", "core", "parsers", "evaluators", "privacy", "ai"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))
