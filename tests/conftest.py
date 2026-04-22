"""Pytest configuration — add src/ to sys.path for imports."""

import sys
from pathlib import Path

# Allow `from trajectory.xxx import yyy` without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
