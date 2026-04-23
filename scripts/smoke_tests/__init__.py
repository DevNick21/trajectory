"""Smoke tests — live-API sanity checks for each system slice.

Not a replacement for `tests/` (pytest, fixture-only, zero API cost).
These exercise the real Anthropic / Companies House / gov.uk / scrape
paths so defects that only surface against real traffic come out here
rather than during the demo.

Run a single slice:
    python -m scripts.smoke_tests.run_all --only verdict

List everything:
    python -m scripts.smoke_tests.run_all --list

Run only the $0 tests:
    python -m scripts.smoke_tests.run_all --cheap

Run the full suite (budget ~$5-10 for a full forward_job exercise):
    python -m scripts.smoke_tests.run_all
"""
