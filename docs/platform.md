# Running the complete local platform

The API queues tasks in SQL storage. A separate worker prepares a filtered snapshot,
analyzes it and calls local Ollama for a plan. Approval authorizes that exact snapshot,
its declared paths, selected test environment, and a bounded attempt budget. Development,
tests and read-only review repeat within that scope until validation succeeds or the
budget ends. The original repository changes only after explicit delivery approval.

## Start

From the project directory, install with `.venv\Scripts\python.exe -m pip install -e .[dev]`
and build with `scripts\frontend.ps1 build`. Configure a locally pulled model in `.env`:
`ASE_OLLAMA_MODEL=qwen2.5-coder:3b` (a larger capable local model usually produces better results).

Build the offline test image once:

```powershell
docker build -t ase-runner:local -f containers/runner.Dockerfile .
```

Run these in separate terminals:

```powershell
.\scripts\run-platform.ps1 api
.\scripts\run-platform.ps1 worker
```

Open http://127.0.0.1:8765/ui/ and use **New task**. Review the plan, choose Docker
tests, and approve. Task history, source, diffs, review, progress and outcomes survive
browser refresh. `/docs` contains the API schema; `/evaluation` returns observed metrics.
The old `monitor:create_monitor_app` is retained for compatibility tests; use the
`platform:create_platform_app` factory for this UI.

## Persistence and recovery

SQLite (`sqlite:///engineering.db`) is the zero-setup default. For PostgreSQL:

```powershell
docker compose up -d postgres
```

Set `ASE_DATABASE_URL=postgresql+psycopg://engineering:local-development-only@127.0.0.1:55432/engineering`
in `.env`, then restart API and worker. This starts a new history; it does not migrate
existing SQLite rows. The Compose password is for loopback development; set
`ASE_POSTGRES_PASSWORD` and a matching database URL for other installations.

Schema tables initialize on startup. This is the initial platform schema; future schema
changes require migrations before deployment. Back up the database **and** `.workspaces`
to preserve retained source evidence and delivery exports. Do not delete volumes to restart.

Workers claim jobs using transactional fencing and renew leases. Queued jobs and pending
approvals survive restart. An expired in-flight job stops as failed with its retained
checkpoint; it is never blindly repeated after possibly completed writes. Retry creates
a fresh task and workspace. Cancellation is cooperative: generation may finish before
the worker observes cancellation, but ownership is checked before snapshot writes and
before starting subsequent nodes. A process interrupted during a file write can leave
a partial isolated snapshot; inspect it and retry rather than delivering it.

## Tests and delivery

Default runner supports unittest and pytest. Tests execute offline as an unprivileged
user with no capabilities, a read-only root/source, bounded temporary storage, memory,
CPU, process count, time and output. Source is copied to ephemeral storage. Docker
failures are recorded as errors; execution never silently falls back to the host.
Dependencies must be built into a project-specific runner image. For npm, build the
Node base using `docker build -t ase-node-runner:local -f containers/node-runner.Dockerfile .`
and set `ASE_DOCKER_IMAGE=ase-node-runner:local`, then restart the worker. This base runs
dependency-free Node tests; add project dependencies to a derived image and expose them
to the ephemeral project (for example via `NODE_PATH` for CommonJS imports). For npm, provide an
image with Node, preinstalled dependencies and the same trusted `/opt/ase/runner.py`
entrypoint; `npm test` runs with `CI=true`. Local unittest/pytest is an explicit trusted
repository option and runs on this computer. Empty or skipped tests cannot yield success.

Delivery requires successful tests, model approval and unchanged artifact hashes:

* **Create commit:** creates an independent Git repository with a filtered baseline
  and a reviewed-change commit; downloads a ZIP containing its Git history.
* **Apply to original:** previews changed paths, checks original contents still match
  the baseline, then applies the approved files. It refuses to overwrite newer work.
* **Create draft PR:** import a GitHub repository first and set `ASE_GITHUB_TOKEN`
  with appropriate Contents/Pull requests permissions. Explicit confirmation creates
  a dedicated branch and draft PR. Base-tree updates preserve unimported binary files;
  a moved base branch requires re-import. No automatic merge occurs.

Repeated completed delivery requests reuse their recorded result. If the API crashes
during delivery, the task retains `publishing=true`; inspect Git/local artifacts before
an operator clears that field in the database. It deliberately refuses blind duplicate
publishing. GitHub remote delivery requires live credentials and account verification.

## Evaluation

`python -m autonomous_engineering.application.evaluation` exports real observed success,
test-run pass rate, agent time, attempts and Ollama token evidence. Unknown test counts,
missing token counts and monetary cost remain unknown, rather than being invented.
Metrics cover the most recent 500 tasks, including cancellations in terminal outcomes.

Run an opt-in real-model benchmark on the bundled disposable fixture:

```powershell
$env:ASE_DATABASE_URL='sqlite:///benchmark.db'
python -m autonomous_engineering.application.benchmark examples/benchmarks.json --approve-fixture-plans
```

The dataset declares approved paths. Any model plan outside that allowlist is cancelled.
Only isolated snapshots are edited. Use an independent database with no queued user jobs.
The small fixture measures one narrow behavior; it is not a general coding-quality benchmark.

## Deployment limits

This release targets a single trusted operator on a local machine. Bind API to loopback.
There is no multi-user authentication, tenant isolation, remote Ollama, production secret
manager, generalized dependency installation, or automatic merge/deploy. SQL storage
supports separate workers, but repository storage must be shared at identical paths.
Keep Docker access in the trusted worker; never mount its socket into test containers.
Filtering excludes credentials, Git internals, links, binaries and oversized files, so
large/binary-heavy projects may need a different repository adapter. Model approval and
passing tests are useful evidence, not proof of correctness or security.
