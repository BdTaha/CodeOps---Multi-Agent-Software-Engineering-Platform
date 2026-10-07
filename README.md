# Engineering Lab

A local software engineering system with a React workspace and a Python/FastAPI/LangGraph backend.
It analyzes repositories, plans with local Ollama, applies approved changes to isolated snapshots,
runs tests in Docker, reviews results and performs bounded repairs. SQL-backed tasks and independent
workers retain history and progress across refresh and restart.

## Quick start on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\scripts\frontend.ps1 install
.\scripts\frontend.ps1 build
ollama pull qwen2.5-coder:3b
docker build -t ase-runner:local -f containers/runner.Dockerfile .
```

Set `ASE_OLLAMA_MODEL=qwen2.5-coder:3b` in `.env` and keep Ollama running.
Run the API and worker in separate terminals:

```powershell
.\scripts\run-platform.ps1 api
.\scripts\run-platform.ps1 worker
```

Open [the dashboard](http://127.0.0.1:8765/ui/). Create a focused task, inspect the plan,
choose the test environment and attempt limit, then approve. Successful changes can be exported
as real Git commits, applied to unchanged original files, or explicitly delivered as a draft
GitHub PR after repository import and credential setup.

SQLite is the default. PostgreSQL can be started with `docker compose up -d postgres` and the
matching `ASE_DATABASE_URL` from `.env.example`. See [the platform runbook](docs/platform.md)
for configuration, recovery, delivery, evaluation and deployment boundaries.

## Verification and evaluation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\frontend.ps1 build
```

Enable `ASE_INTEGRATION_DOCKER=1` for real container tests and set
`ASE_INTEGRATION_DATABASE_URL` to a dedicated PostgreSQL test database for storage verification.
The integration tests create retained task rows. Use a distinct temporary directory with
`--basetemp` when sandbox and ordinary terminal runs have different Windows ownership.

Observed metrics are available at `/evaluation`; API documentation is at `/docs`.
Run `python -m autonomous_engineering.application.evaluation` to export metrics.
The runbook includes an explicit fixture benchmark command using the real local model.
Unknown test counts, missing token evidence and monetary costs remain unknown.

## Boundaries

This release serves a trusted local operator and binds to loopback. It does not provide
multi-user authentication or production tenant isolation. Tests and model approval are
recorded evidence, not guarantees. Imports and workspaces are bounded UTF-8 snapshots;
binaries, secrets, links and Git internals are excluded. Project dependencies must be
built into custom runner images. GitHub delivery needs a token and explicit confirmation;
there is no automatic merge or deployment.

Earlier documents in `docs/phase-*.md` describe historical milestones. The platform runbook
is the current operational reference. The legacy monitor remains for compatibility.
