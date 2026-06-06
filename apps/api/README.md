# AskPicky API App

This app is the thin runtime boundary for the public API.

The importable backend package lives in `packages/engine/src/askpicky`. Keep
domain logic, agents, parsers, evaluators, privacy utilities, and storage in
the engine package. Keep this app limited to launch and deployment concerns.

Run locally from the repository root:

```bash
python scripts/run_api.py
```

Run the API and web app together:

```bash
python scripts/run_local_dev.py
```
