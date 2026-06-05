# Public API Surface

Core local routes:

- `POST /api/job-analysis` for pasted job-description first-pass analysis.
- `POST /api/sessions/forward_job` for the full URL-based research stream.
- `GET /api/applications` for the manual application tracker.
- `POST /api/assist/*` for evidence-backed answer coaching.
- `GET /api/privacy/export` and `DELETE /api/privacy/*` for local controls.

Generated OpenAPI files are written to `apps/web/src/generated`.
