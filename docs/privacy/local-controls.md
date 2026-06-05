# Local Privacy Controls

The public engine exposes local privacy controls under `/api/privacy/*`.

- `GET /api/privacy/export` exports user-scoped local rows.
- `DELETE /api/privacy/me` hard-deletes user-scoped local rows.
- `DELETE /api/privacy/cv` deletes CV-derived career entries.
- `DELETE /api/privacy/applications/{session_id}` deletes one saved application
  and related local traces.

The local engine does not implement hosted backups, managed retention systems,
dedicated email storage, billing records, or cloud audit infrastructure.
