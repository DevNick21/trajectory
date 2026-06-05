# Local Engine

The local engine runs from the repository root:

```bash
pip install -e .
pip install -r requirements.txt
python scripts/run_api.py
cd apps/web && npm install && npm run dev
```

The Python package source lives at `packages/engine/src`. The frontend lives at
`apps/web`. The browser companion lives at `apps/extension`.

BYOK/local-provider support belongs in the public engine. Managed AI credits,
hosted quota systems, billing, and production model routing do not.
