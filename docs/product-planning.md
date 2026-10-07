# Goal → Project plan → Board

CodeOps adds product planning above its existing engineering execution layer.
A product goal is not a coding execution request. Planning does not edit files,
run tests, assign people or agents, or create GitHub branches or pull requests.

## Architecture and data flow

1. Select an existing registered project and submit a goal in Planning.
2. `POST /projects/{project_id}/plans` validates the goal and saves a queued
   `ProjectGoal` in the existing SQL database. It returns immediately with 202.
3. The existing independent worker processes execution jobs first, then product
   planning jobs. Product jobs have their own claim, heartbeat and fenced lease.
   A refresh or lost HTTP connection does not own or stop model generation.
4. `ProductPlanningAgent` calls `OllamaProductPlanProvider`, which reuses the
   loopback-only Ollama JSON-schema adapter. The context includes the goal and
   registered project name, description and stack, not the host repository path.
5. Pydantic validates every required field, unique epic/task references,
   positive finite effort estimates, valid dependencies and an acyclic graph.
   Invalid output gets one retry with validation feedback. Two invalid results
   fail explicitly; no missing title, estimate or acceptance criterion is filled in.
6. A validated draft is saved atomically as epics, engineering tasks, dependencies
   and acceptance criteria. Server-generated UUIDs, timestamps, initial Backlog
   status and project-local `CO-N` keys are metadata, not generated feature content.
7. The UI loads the latest goal/plan and polls while queued or generating. It
   groups tasks by epic in Planning and by status in Board. Task details expose
   descriptions, dependencies and acceptance criteria; empty criterion boxes are
   requirements and do not claim that any implementation has passed.
8. A manual status PATCH includes the task revision. A stale revision returns 409
   and the UI reloads current data rather than overwriting another window's work.

The existing `domain.tasks.TaskRecord` and `tasks` SQL table still represent
autonomous coding execution. New `EngineeringTask` records have a nullable
`execution_run_id` reserved for a later bridge; it remains null in this phase.
There is no automatic EngineeringTask → Developer connection.

## Persistence

`PlanningStore` shares `TaskStore.engine` and SQLAlchemy metadata. It adds:

- `product_goals`: goal, generation status, lease, attempt count, model, error,
  and plan title/summary/assumptions.
- `product_epics`: ordered plan epics.
- `engineering_tasks`: project-local task number, epic, metadata, status and revision.
- `engineering_task_dependencies`: task-to-task references.
- `engineering_acceptance_criteria`: ordered task requirements.

New tables are added to the current SQLite/PostgreSQL schema without replacing
or deleting execution tables. At most one plan may be active per project.
Creating another plan retains earlier rows and continues project task numbering.
The first UI shows the latest plan; it does not yet include a plan-history picker.
An interrupted worker lease becomes a clear failed goal. Submit again to retry.

## API

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/projects/{project_id}/plans` | Queue `{"goal":"…"}`; return goal status |
| GET | `/projects/{project_id}/plan` | Latest goal and its plan, or null before the first goal |
| GET | `/projects/{project_id}/engineering-tasks` | Tasks from the latest plan |
| GET | `/engineering-tasks/{task_id}` | Persisted individual task |
| PATCH | `/engineering-tasks/{task_id}/status` | `{"status":"planned","revision":0}` |

Statuses are `backlog`, `planned`, `in_progress`, `review`, `done`. Changes are
manual and can move in either direction. Dependencies are planning references,
not automatic restrictions on manual status changes. Priority is low, medium,
high or urgent. Areas are Backend, Frontend, Database, DevOps, QA or General.

## Run and verify

Keep Ollama running and configure a locally pulled model in `ASE_OLLAMA_MODEL`.
The same model currently powers execution and product planning. Build the UI,
then start the existing API and worker in two terminals from the project root:

```powershell
.\scripts\frontend.ps1 build
.\scripts\run-platform.ps1 api
# Second terminal:
.\scripts\run-platform.ps1 worker
```

Open http://127.0.0.1:8765/ui/. Select a project and enter:

> Add authentication with registration, login, password reset and role-based access.

Click **Plan with CodeOps**. Inspect epics and task details, refresh to verify
persistence, open Board and change a task status. Refresh again to verify it.
If a request remains queued, start the worker. Model failures appear clearly on
the planning page. The coding workflow is still available under Engineering,
with Code review, Results, and Metrics & history alongside it. GitHub import is
still available in the existing engineering overview; delivery remains in Results.
Execution preview data remains explicitly labelled and is not used for planning.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_product_planning.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\frontend.ps1 build
```

Tests use explicitly isolated fixture providers, not production fallback plans.
They cover invalid outputs, bounded retries, dependency cycles, persistence across
reopen, independent worker completion, lease fencing, status conflicts and origin
checks. The existing execution tests exercise the preserved coding workflow.

## Limits and next phase

Estimates are rough engineering effort, not guaranteed dates or team capacity.
Plans need human inspection; schema validation cannot guarantee completeness or
model quality. This phase uses the goal and project metadata, without repository
analysis by the product planner. Large goals are bounded to 8 epics and 32 tasks.
There are no accounts, squads, assignments, learning, sprint optimization,
preview deployment, approval bridge, automatic merge or deployment.

Newly generated tasks are bounded to 24 estimated hours each so large work must
be split. The model is encouraged to prefer smaller tasks. Older saved estimates
are still readable. This bounds size; it does not establish estimate accuracy.

The next phase should let a person refine the plan and select one EngineeringTask
for an explicitly approved ExecutionRun, carrying its acceptance criteria into
the existing coding planner. This bridge is deliberately not implemented here.

## Files added or modified in this phase

Added:

```text
src/autonomous_engineering/domain/product_planning.py
src/autonomous_engineering/agents/product_planner.py
src/autonomous_engineering/infrastructure/ollama_product.py
src/autonomous_engineering/infrastructure/planning_store.py
src/autonomous_engineering/application/product_planning.py
src/autonomous_engineering/api/planning.py
frontend/src/productTypes.ts
frontend/src/productApi.ts
frontend/src/ProjectHome.tsx
frontend/src/Planning.tsx
tests/test_product_planning.py
docs/product-planning.md
```

Modified:

```text
src/autonomous_engineering/platform.py
src/autonomous_engineering/application/worker.py
src/autonomous_engineering/infrastructure/ollama.py
frontend/src/App.tsx
frontend/src/Dashboard.tsx
frontend/src/types.ts
frontend/src/useWorkbench.ts
frontend/src/styles.css
frontend/index.html
README.md
```

The shared Ollama adapter keeps its existing execution defaults and now permits
product-specific output limits and preservation of bounded validation diagnostics.
The remaining uncommitted developer/reviewer changes predate this product phase.
