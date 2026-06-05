"""Pytest configuration - add the engine source root to sys.path."""

import sys
from pathlib import Path

# Allow `from askpicky.xxx import yyy` without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "engine" / "src"))
