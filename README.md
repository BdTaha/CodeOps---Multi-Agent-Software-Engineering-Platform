# CodeOps

A local engineering management and software delivery platform with a React workspace and a Python/FastAPI/LangGraph backend.
Its default experience turns a project goal into persisted epics and engineering tasks, with estimates,
dependencies, acceptance criteria and a manually managed board. See [product planning](docs/product-planning.md).
Teams adds shared workspace identities, project memberships, squads, skills, global planning capacity,
task ownership and explainable assignment suggestions. See [teams and capacity](docs/teams-and-capacity.md).
It analyzes repositories, plans through a configurable model gateway, applies approved changes to isolated snapshots,
runs tests in Docker, reviews results and performs bounded repairs. SQL-backed tasks and independent
workers retain history and progress across refresh and restart.
The intended cloud route is NVIDIA NIM with `moonshotai/kimi-k3` and local Ollama
fallback for availability failures only. Existing Ollama-only environments remain
compatible. **Settings · Models** lets users add NVIDIA, Ollama, OpenAI-compatible,
Anthropic, Gemini, and custom API connections, load models, and apply routing without
restarting workers. Credentials are encrypted on the backend. See
[provider settings](docs/provider-settings.md) and [gateway policy](docs/model-gateway.md).

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
This retains local-only compatibility mode. To enable NVIDIA/Kimi K3 instead,
add a NVIDIA connection in **Settings · Models**, enter your key, select the model,
and click **Apply routing**. You can keep Ollama as the explicit fallback.
Environment-based setup is also supported; environment edits require API/worker restart.
Docker is needed for container-based coding tests; goal planning and the board
can run with only Ollama, the API and the worker.
Run the API and worker in separate terminals:

```powershell
.\scripts\run-platform.ps1 api
.\scripts\run-platform.ps1 worker
```

Open [CodeOps](http://127.0.0.1:8765/ui/). Select an existing project, enter a goal in Planning,
and click **Plan with CodeOps**. Open Board to inspect tasks and change their statuses. Plans and
status changes survive refresh; effort estimates are not guaranteed delivery times.
Open **Teams → Workspace members** to create identities once, then **Project teams** to create
squads and add existing members. Assign tasks from their Board details.
Human load is global across projects, with reserved effort and a project breakdown. AI queued
ownership is separate from real execution reservations. Use **Run with CodeOps** on an eligible
AI developer task, approve its coding plan, then review and accept the result. Delivery remains
explicit. See [the execution bridge](docs/task-execution-bridge.md).
The default Acceptance review tab now maps each requirement to retained per-run
evidence, distinguishes Verified / Supported / Unverified and conflicts, and
requires acknowledgment for unresolved or unavailable evidence before acceptance.
See [acceptance evidence](docs/acceptance-evidence.md).
Project Preview settings and the review Preview tab now support isolated local
Python/Node environments with loopback URLs, bounded lifecycle and cleanup. Run
`./scripts/run-platform.ps1 preview` alongside API/worker after building the
dedicated images. See [local previews](docs/local-previews.md).
**Recommend assignments** proposes a plan; only **Apply suggested assignments** saves it.
Team management does not require Ollama or Docker and does not start coding execution.

The existing coding workflow lives under Engineering. Create a focused execution task, inspect the plan,
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
