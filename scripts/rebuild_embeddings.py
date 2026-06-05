"""Rebuild the FAISS embedding index from the career_entries table.

Run after bulk data imports or if the index file is deleted.

Usage: python scripts/rebuild_embeddings.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
for _package in ("engine", "core", "parsers", "evaluators", "privacy", "ai"):
    sys.path.insert(0, str(_ROOT / "packages" / _package / "src"))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def rebuild() -> None:
    from askpicky.storage import Storage

    storage = Storage()
    await storage.initialise()

    log.info("Loading all career entries from DB…")
    entries = await storage.get_all_career_entries()
    log.info("Found %d entries", len(entries))

    if not entries:
        log.warning("No career entries found. Nothing to index.")
        await storage.close()
        return

    log.info("Rebuilding FAISS index…")
    await storage.rebuild_index(entries)
    log.info("Index rebuilt with %d vectors", len(entries))

    await storage.close()
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(rebuild())
