# CodeOps

CodeOps is an AI-assisted engineering management and multi-agent delivery platform
that turns product goals into reviewable engineering work.

## Why CodeOps

Keep management decisions, implementation and human verification in one traceable
workspace. Generated plans are proposals: people edit and approve them before work
becomes actionable. Every coding run retains its plan, diff, tests, review,
evidence, human decision and explicit delivery artifact.

## Core workflow

```text
Product goal → Repository-grounded draft → Human plan approval
→ Board / Teams → Human + AI ownership → Run with CodeOps
→ Repository analysis → Coding plan → Human coding approval
→ Developer → Tests → Reviewer / bounded repair → Acceptance evidence
→ Optional preview → Human accept or Request Changes → Explicit Git / draft PR
```

Drafts use T refs. Only approval creates permanent CO keys and actionable tasks.
Older approved work remains visible while another draft is generated. Estimates
are rough effort, not guaranteed delivery time.

## Architecture and features

React/TypeScript provides Planning, Board, Teams and a task-centered Engineering
workspace. FastAPI/Pydantic validates boundaries; SQLAlchemy persists SQLite or
PostgreSQL state; independent LangGraph workers perform analysis/coding/tests/
review. A separate worker owns previews. See [architecture](docs/architecture.md).

* Repository observations, editable drafts, revisions and atomic approval.
* Shared workspace members, project squads, global human capacity and explainable
  assignment suggestions; AI queues are separate from runtime concurrency.
* Overview, Plan, Files, highlighted unified/split Diff, Tests, Review, Acceptance,
  Preview and History, with actions appropriate to retained lifecycle state.
* Evidence, Request Changes/new runs, human acceptance and explicit Git delivery.

## Safety and human control

Product and coding plans require separate human approvals. AI works in isolated
snapshots; tests/previews use isolated environments. Original source stays
unchanged until explicitly choosing local apply. Acceptance is human-controlled;
delivery is separate and explicit. There is no automatic merge or deployment.
Fallback is observable. Missing evidence never becomes fabricated verification.
Tests and model review provide evidence, not guarantees of correctness.

## Model providers

**Settings · Models** supports NVIDIA NIM, Ollama, OpenAI-compatible, Anthropic,
Gemini and custom connections using existing supported protocols. Test/load models
or enter an exact ID; choose primary and optional fallback; **Apply routing**.
Keys remain encrypted on the backend; settings apply without worker restart.
Environment-based `ASE_*` setup stays compatible. The NVIDIA route supports Kimi
configuration; availability depends on account/provider. Ollama needs no cloud
key. Use a model capable of structured JSON; small models can fail validation or
produce weak plans. See [settings](docs/provider-settings.md) and
[fallback policy](docs/model-gateway.md).

## Local preview

Reviewed Python/Node applications can run in one temporary Docker environment
with loopback URL, health checks, TTL and cleanup. Preview copies filtered reviewed
source to its own volume, never mounts the host repository and never decides
acceptance. External-service/multi-container apps are outside v1.
See [preview profiles and images](docs/local-previews.md).

## Screenshots

Capture actual Draft Planning, Board, Teams, Engineering Diff, Acceptance, Preview
and Models screens using [this checklist](docs/screenshots/README.md). No
illustrative image is presented as a verified product state.

## Quick start (Windows)

Python 3.11+ (CI 3.12), Node 22.12+ (CI 22.18.0), pnpm 11.25.0, Git,
and Docker Desktop Linux engine for container tests/previews.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\scripts\frontend.ps1 install
.\scripts\frontend.ps1 build
ollama pull qwen2.5-coder:3b
docker build -t ase-runner:local -f containers/runner.Dockerfile .
docker build -t codeops-preview-python:local -f containers/preview-python.Dockerfile .
```

Configure `ASE_OLLAMA_MODEL` or Settings · Models. Keep Ollama running for its
local route. The lightweight 3b model is a starting point, not a quality guarantee.
Repositories must be inside `ASE_REPOSITORY_ROOT`, outside `ASE_WORKSPACE_ROOT`.
Run each service in a separate terminal:

```powershell
.\scripts\run-platform.ps1 api
.\scripts\run-platform.ps1 worker
.\scripts\run-platform.ps1 preview
```

Open [CodeOps](http://127.0.0.1:8765/ui/). Register source in Projects, enter a
Planning goal, edit/save the draft and approve it. Board/Teams then expose tasks.
Create an AI developer and squad, assign eligible work and start its execution.
Follow [the complete demo](docs/v1-demo.md) for approvals, preview, changes,
acceptance and delivery.

SQLite is default. `docker compose up -d postgres` starts optional local
PostgreSQL; switching backends does not transfer existing rows. Back up SQL and
retained workspaces before upgrading; restart API, worker and preview together.
Migrations are additive; legacy ready plans are read as approved.
See [runbook](docs/platform.md).

## Testing and CI

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
pnpm install --frozen-lockfile
pnpm test
pnpm build
```

[GitHub Actions](.github/workflows/ci.yml) runs backend/frontend checks on push
and PR. Normal tests use explicit provider fixtures/transports and need no model
keys, Ollama, PostgreSQL or Docker. Integrations are opt-in:
`ASE_INTEGRATION_DATABASE_URL` for a disposable test database,
`ASE_INTEGRATION_DOCKER=1` for runners, `ASE_INTEGRATION_PREVIEWS=1` for previews.
Never point integrations at your working database; tests can retain rows.
Windows ownership differences may need a new `--basetemp=.workspaces/test-run`.
See [actual verification](docs/verification.md).

## Current limitations and roadmap

v1 is feature-frozen for one trusted local operator, without multi-user accounts
or tenant isolation. Context/snapshots are bounded UTF-8 samples; filtering cannot
identify every hardcoded secret. Model quality varies; validation errors remain
visible. Offline dependencies need custom runner images. Preview supports one
Python/Node service, without external databases or outbound runtime APIs.
Request Changes starts from registered source with prior feedback/history; it
does not automatically apply old output. GitHub delivery needs import, credentials
and an explicit action. No automatic acceptance, merge or deployment.

Roadmap only: dispatch/scheduling, accounts/RBAC, analytics/billing, multi-container
or cloud previews, per-agent routing, model benchmarks, marketplace and IDE/chat
integration. Historical phase documents retain milestone history; current
architecture/runbooks describe v1.
