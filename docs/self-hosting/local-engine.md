# Local Engine

The local engine runs from the repository root:

```bash
pip install -e .
pip install -r requirements.txt
export ASKPICKY_LOCAL_MODE=1
python scripts/run_api.py
cd apps/web && npm install && npm run dev
```

On Windows PowerShell use:

```powershell
$env:ASKPICKY_LOCAL_MODE = "1"
python scripts/run_api.py
```

The FastAPI application package lives at `packages/engine/src`. Public package
boundaries live under `packages/core`, `packages/parsers`,
`packages/evaluators`, `packages/privacy`, and `packages/ai`. The frontend
lives at `apps/web`. The browser companion lives at `apps/extension`.

SQLite is the default local persistence target at `data/askpicky.db`. The
local smoke test is:

```bash
python -m scripts.smoke_tests.run_all --only self_host_local
```

BYOK/local-provider support belongs in the public engine. Managed AI credits,
hosted quota systems, billing, and production model routing do not.
