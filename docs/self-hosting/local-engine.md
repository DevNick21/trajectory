# Local Engine

The local engine runs from the repository root:

```bash
pip install -e .
pip install -r requirements.txt
cd apps/web && npm install && cd ../..
python scripts/run_local_dev.py
```

`scripts/run_local_dev.py` sets `ASKPICKY_LOCAL_MODE=1` and
`DEMO_USER_ID=local-user` when they are not already set. It starts:

- FastAPI at `http://127.0.0.1:8000`
- Vite at `http://127.0.0.1:5173`

For split terminals, run:

```powershell
$env:ASKPICKY_LOCAL_MODE = "1"
python scripts/run_api.py
npm run --prefix apps/web dev
```

In Git Bash, use shell environment syntax:

```bash
export ASKPICKY_LOCAL_MODE=1
python scripts/run_local_dev.py
```

If Windows blocks port 8000, choose another API port:

```bash
API_PORT=8011 python scripts/run_local_dev.py
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
