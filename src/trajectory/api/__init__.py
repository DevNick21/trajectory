"""FastAPI surface for the web app.

Web-primary half of the dual-surface architecture (MIGRATION_PLAN.md
ADR-001). Telegram bot stays on long-polling; this module is the
HTTP + SSE entry point for the React frontend.

Run: `uvicorn trajectory.api.app:app --reload --port 8000`
or:  `./scripts/run_api.sh`
"""
