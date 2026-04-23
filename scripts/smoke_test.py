"""Compat shim — forwards to the new `scripts.smoke_tests` package.

Kept so old habits (`python scripts/smoke_test.py`) still work. The
richer, per-slice smoke tests now live in `scripts/smoke_tests/` and
are orchestrated by `scripts/smoke_tests/run_all.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `scripts` importable as a package so `python scripts/smoke_test.py`
# can find `scripts.smoke_tests.run_all` without a PYTHONPATH dance.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.smoke_tests.run_all import main  # noqa: E402


if __name__ == "__main__":
    # Default to the verdict slice for backward compatibility with the
    # old monolithic smoke_test.py behaviour.
    if len(sys.argv) == 1:
        sys.argv.extend(["--only", "verdict"])
    sys.exit(main())
