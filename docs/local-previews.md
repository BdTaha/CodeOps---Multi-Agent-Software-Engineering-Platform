# Local preview / verification environments

## Architecture and lifecycle

This layer extends the existing EngineeringTask execution bridge and acceptance
evidence. It does not run another developer/test/reviewer pipeline. A preview is
a temporary human review surface, never an acceptance decision, automated
criterion verification or deployment.

An explicit POST creates a durable **queued** attempt. The separate preview
worker claims a bounded startup lease, materializes eligible text from the final
successful workspace into a Docker-owned volume, prepares dependencies/builds,
removes the builder, creates the serving container, discovers Docker's assigned
loopback port and checks the configured HTTP endpoint. **Ready** is persisted only
after a 2xx response. The builder and server are sequential; at most one container
exists for an environment at a time. No Compose or service graph is involved.

Statuses: queued → building → starting → ready → stopping → stopped/expired.
Startup or health failures end in failed after cleanup. If Docker cleanup cannot
be confirmed, stopping remains active, the URL is hidden, resources count against
the limit and a failure reason is retained for retry. Development remains
Succeeded and the EngineeringTask remains Review.

An AI runtime slot is already released before previewing. Preview work does not
reserve an AI slot or occupy the engineering worker. The preview service has a
startup loop plus an independent reconciliation thread, keeping cleanup/TTL
responsive during another application's bounded build. The existing global
resource lock fences races without incrementing Teams recommendation revisions.

Start requires the latest linked succeeded execution, task Review, pending human
review, a valid retained reviewed workspace, an enabled non-none project profile
and no declared external service requirement. Duplicate starts return the current
active attempt. A nullable unique active_execution_id and the shared transactional
fence protect duplicate/racing starts on SQLite and PostgreSQL. Workspace limit
defaults to three active previews, separate from AI concurrency.

## Profiles, persistence and migration

Two additive tables are created under the existing startup migration fence:

* **preview_profiles:** UUID id, unique project FK, validated profile JSON,
  revision and creation timestamp. A missing profile means no interactive preview.
* **execution_previews:** UUID id; EngineeringTask, linked execution and profile
  FKs; run ID; frozen profile snapshot; lifecycle status; nullable unique active
  execution ID; container ID and host port; source digest; creation/start/ready/
  stop/expiry timestamps; failure reason; bounded log tail; startup owner/lease and
  requested terminal reason.

The profile contains name, type (web/api/static/none), constrained runtime
(python/node), enabled flag, build_commands (argv arrays), start_command (argv),
container_port (1–65535), health/open paths, explicit non-secret environment,
timeout_seconds (5–300), ttl_minutes (1–120), build_network (false by default) and
requires_external_services. There is no host image/mount/privilege selector.
Settings-level base images are trusted operator configuration, not repository
metadata or model output. Profile updates use optimistic revision checks; existing
attempts retain the previous immutable profile snapshot.

Migration is additive, fenced and idempotent. Existing tasks, executions, evidence,
acceptances and history stay intact. There is no backfill or automatic start for
old runs. Preview history is separate for every attempt and remains after cleanup.

## Source and artifact integrity

The existing `checked_artifact` and acceptance receipt remain unchanged. Preview
materialization checks the receipt before and after reading eligible files through
the existing bounded RepositoryReader. Source bytes are archived with safe relative
paths and unprivileged ownership, then copied through Docker into an isolated
volume. The original repository and canonical reviewed workspace are never mounted
into preview containers, writable or otherwise. Neither dependency installation
nor runtime caches, databases or logs can write into those artifacts.

Existing snapshot filters exclude Git metadata, host credentials, node_modules,
caches, symlinks/reparse points and secret-named files. Preview copying additionally
omits all .env-prefixed files, including examples. No host environment, GitHub
token, AWS/SSH credentials or configured CodeOps provider secret is injected.
Explicit environment names are bounded and reject known secret/runtime-control
names; duplicate JSON/environment keys are rejected. Values must be non-secret
configuration supplied by the human. Filtering is not a detector for secrets
hardcoded into otherwise eligible application source.

The source digest records the actual materialized filtered text inventory. It
does not weaken or replace the existing reviewed-file receipt. Binary/oversized
assets excluded by the execution snapshot cannot be recovered by previewing.

## Runtime / security / network policy

Both images use UID/GID 10001, /app working directory, read-only root, dropped
capabilities, no-new-privileges, 1 GiB memory/swap, two CPUs, 256 PIDs and a bounded
256 MiB /tmp. The isolated /app volume is mutable and ephemeral. There are no host
bind mounts, Docker socket, privileged mode, host network or automatically pulled
repository-selected images. Docker logs rotate at 1 MiB × two files; persisted
tails are bounded to 16 KiB. Volume disk usage is not quota-enforced in this MVP.

Build networking defaults to none. Enabling build_network permits dependency and
repository build scripts to access Docker's bridge network; those scripts can use
the network and see the filtered preview source. This permission never grants host
filesystem access or automatic credentials. Dependencies are installed only inside
the builder: Node uses npm ci and requires package-lock.json; Python installs
requirements.txt into /app/.preview-deps. Additional build steps use structured
argv, not shell concatenation. The resulting volume is used by the serving image.

The runtime has its own labeled bridge with inter-container connectivity disabled,
one random published port bound explicitly to **127.0.0.1**, and the restrictive
vendored seccomp policy documented in `containers/preview-seccomp.md`. New outbound
connections, IP datagram/raw sockets and TCP Fast Open are restricted while inbound
HTTP and interface discovery remain available. Projects requiring outbound API,
database, Redis or similar runtime connections are unsupported. Browser-side
requests are governed by the browser, not the server container's syscall policy.
Docker containers share a kernel and are not a guarantee against kernel exploits.

The health checker uses the persisted Docker-selected port, disables proxies and
redirect following, and accepts only a local configured path with a 2xx response.
No public hostname, iframe, request builder or automated browser validation exists.

## Recovery and human actions

Containers, volumes and networks carry preview, execution, run and workspace
ownership labels. The namespace includes canonical database/workspace identity,
excluding the database password. Reconciliation inspects only matching resources
and verifies full ownership before removal. It preserves healthy unexpired Ready
containers across API/worker restart, detects exited/missing/unhealthy containers,
cleans expired attempts and stale startup leases, and removes clearly labeled
orphans. Unrelated Docker containers are not touched.

TTL starts at queue creation (default 30 minutes). The preview worker must be
running to enforce TTL or cleanup; Docker has no independent TTL mechanism. If
the worker is down, restart it. Interrupted startup is failed and cleaned after
its bounded lease expires rather than rerun implicitly. Restart creates a fresh
attempt once cleanup is confirmed; the latest pending-review eligibility is
rechecked. API/browser restart never causes recomputation or startup on GET.

**Accept result:** the UI requests Stop and waits for confirmed cleanup before
submitting the existing acceptance action. The backend independently refuses
acceptance while any preview remains active/stopping, keeping the task in Review.
If cleanup exceeds the UI's one-minute wait, it reports pending cleanup and the
human can accept again after the worker finishes. A run/profile race is checked
again by the acceptance transaction. No automatic acceptance occurs.

**Request changes:** the existing transaction atomically marks the old run's
previews stopping before creating the new execution. They cannot promote to Ready
or restart; the new run gets independent evidence and preview history. Opening or
stopping previews never changes criterion states. Git/GitHub delivery remains a
separate accepted-result action.

## API and frontend

* GET/PUT `/projects/{id}/preview-profile`: inspect/save with revision validation.
* POST `/projects/{id}/preview-profile/validate`: schema-only validation; no commands.
* GET/POST `/engineering-tasks/{id}/preview`: current profile, eligibility,
  current/history; enqueue using task revision and execution_task_id.
* POST `/previews/{id}/stop`: durable cleanup request.
* POST `/previews/{id}/restart`: new attempt, after cleanup, using current task/run.
* GET `/previews/{id}/logs`: retained bounded logs and failure reason.

Mutation routes retain the same-origin local workspace restriction. Builds and
health waits never run in an API request. Existing raw evidence routes are reused.

Projects offers **Preview settings** for each project, with editable Vite/FastAPI/
static examples. The existing result-review tabs add **Preview** alongside the
default Acceptance tab. It shows lifecycle, loopback URL, start/open/restart/stop,
timestamps, errors, logs and historical attempts. API profiles offer Open API and
configured docs links. Links open separate browser tabs. Disabled/none/unsupported
profiles offer the existing Acceptance/Diff/Tests/AI Review verification package.
Runtime-slot wording continues to say terminal execution releases the slot before
human review; backend AI slot semantics are unchanged.

## Configure and run

Build the trusted runtime images once, from the project root:

```powershell
docker build -f containers/preview-python.Dockerfile -t codeops-preview-python:local .
docker build -f containers/preview-node.Dockerfile -t codeops-preview-node:local .
.\scripts\frontend.ps1 build
```

Keep Docker running. Launch these services in **three separate terminals**:

```powershell
.\scripts\run-platform.ps1 api
.\scripts\run-platform.ps1 worker
.\scripts\run-platform.ps1 preview
```

Open http://127.0.0.1:8765/ui/. Back up engineering.db before upgrading and restart
API/engineering worker together for the additive migration. Preview service
settings: ASE_PREVIEW_PYTHON_IMAGE, ASE_PREVIEW_NODE_IMAGE,
ASE_MAX_ACTIVE_PREVIEWS (default 3), ASE_PREVIEW_POLL_SECONDS (default 2).

**Vite:** enabled web/node, build_commands `[ ["npm","run","build"] ]`,
start_command `["npm","run","preview","--","--host","0.0.0.0","--port","4173"]`,
container_port 4173, health/open `/`, TTL 30. The repository must include its npm
lockfile and build/preview scripts. Enable build networking when npm ci needs to
download packages. Production bundle preview is preferred; a manually configured
dev command is possible, but HMR/websocket configurations are project-specific.

**FastAPI:** enabled api/python, start_command
`["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]`, port 8000,
health `/health` (must actually exist), open `/docs`, TTL 30. Adjust the module to
the project. Declare FastAPI/Uvicorn dependencies in requirements.txt and allow
build networking for downloads. A `/docs` health path is also valid if present.

**Static:** static/python, `["python","-m","http.server","8000","--bind","0.0.0.0"]`,
port 8000, health/open `/`. No dependencies or build steps are necessary for plain
retained HTML. Libraries/CLI/worker projects should use none or remain disabled.

## Test, limits and next phase

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_previews.py
.\.venv\Scripts\python.exe -m pytest
# Optional real Docker lifecycle/framework tests (trusted images built above):
$env:ASE_INTEGRATION_PREVIEWS='1'
$env:ASE_DOCKER_EXECUTABLE='C:\Program Files\Docker\Docker\resources\bin\docker.exe'
# Optional disposable PostgreSQL, never a production database:
$env:ASE_INTEGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/DATABASE'
.\.venv\Scripts\python.exe -m pytest tests/test_previews.py
```

Unit lifecycle tests use an explicit fake Docker transport. Opt-in integration
tests exercise actual Python/Node containers, npm ci, Vite build/preview, FastAPI
dependency installation/docs/health, loopback ports, outbound rejection, source
isolation, artifact acceptance, ownership cleanup and SQLite/PostgreSQL persistence.
Framework integration needs network for dependency downloads. The full suite also
retains direct execution, acceptance evidence, Teams, concurrency and delivery tests.

Limits: Linux Docker and the bundled policy/images are required; text snapshots
may omit assets; Python/Node only; no sidecars, outbound runtime dependencies,
secret management, host install fallback, arbitrary images, guaranteed dev HMR,
disk-volume quotas or automatic framework detection. Cleanup/expiry needs the
preview worker and available Docker. API docs may reference browser-loaded CDN
assets. Preview health means HTTP availability, not requirement correctness.

Recommended next phase: explicit structured runner reports and requirement/test
declarations, or separately scoped richer preview dependency/topology contracts.
Neither is implemented here. There is no browser automation, Playwright feature,
automatic acceptance/PR/merge/deployment, provider switching or task dispatcher.

## Changed files

Added: domain/previews.py; infrastructure/preview_tables.py, preview_store.py,
docker_previews.py; application/preview_worker.py; api/previews.py;
frontend/src/PreviewSettings.tsx and ExecutionPreview.tsx;
containers/preview-python.Dockerfile, preview-node.Dockerfile, preview_runner.py,
preview_runner.mjs, preview-seccomp.json, preview-seccomp.md and seccomp-LICENSE;
tests/test_previews.py and tests/fixtures/preview-vite-package-lock.json; this guide.

Modified: core/config.py; infrastructure/team_migrations.py and
task_execution_store.py; platform.py; frontend/src/ProjectHome.tsx,
TaskExecutionPanel.tsx and product.css; scripts/run-platform.ps1; .env.example;
README. Backend paths are under src/autonomous_engineering/.
