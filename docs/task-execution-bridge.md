# EngineeringTask execution bridge

## Architecture and identifiers

Board ownership remains a management decision. **Run with CodeOps** explicitly
creates a job in the existing `tasks` execution store. The same Worker runs
repository preparation/analysis, coding planning, plan approval, Developer,
Tester, Reviewer and Supervisor repairs. No second execution pipeline or provider
is introduced. Product planning describes what to deliver; coding planning
inspects the actual repository and determines how to implement it.

The canonical execution API identifier is `tasks.id` / `TaskRecord.task_id`.
`WorkflowState.run_id` identifies the isolated workspace and agent traces. They
are different UUIDs. `EngineeringTask.execution_run_id` points to the latest run
UUID, while normalized history links both IDs to the board task and AI identity.

## Schema and startup

One additive table, `engineering_task_executions`, stores:

- `execution_task_id`: primary key / foreign key to the existing execution job.
- `run_id`: unique immutable workspace run ID.
- `engineering_task_id`: indexed foreign key to the originating board task.
- `ai_member_id`: indexed foreign key to the responsible workspace identity.
- `parent_execution_task_id`: preceding run for retry or requested changes.
- `created_at`, `review_state`, `reviewed_at`, `feedback`.

Runtime phase, snapshots, attempts, approval receipts, traces and delivery records
remain in the execution engine. History reads join the canonical execution phase;
they do not persist a second phase value. Identity attribution on each link does
not change when task ownership changes later.

Startup creates this table under the existing SQLite migration write fence or
PostgreSQL advisory lock, including databases already migrated to workspace
identities. No existing table or history is deleted. Back up your database before
upgrade and restart API and worker together. Existing direct engineering jobs
stay unlinked and continue through their original APIs.

## Eligibility and concurrency

Start requires an assigned active AI developer identity, an active project
membership, availability other than offline, an unfinished task, completed
dependencies, no active execution for that task, and an available runtime slot.
There is no dependency override. Busy is an administrative planning setting;
an explicit start is permitted if runtime capacity is available. Busy/offline
identities remain excluded from automatic assignment recommendations.

Slots are **reservations for manually started linked workflows**, including
waiting for coding-plan approval:

| Existing execution phase | Reserves a slot |
| --- | --- |
| queued_planning | Yes |
| planning | Yes |
| awaiting_approval | Yes |
| queued_development | Yes |
| development | Yes |
| succeeded / failed / cancelled | No |

Counting approval waiting prevents a collection of approved plans from later
entering development beyond the identity's concurrency limit. The UI explicitly
calls out these reservations. Final human **result** review, after successful
engine completion, does not consume a slot.

`assigned_queue_depth` still counts all unfinished owned EngineeringTasks.
`active_execution_count` counts linked jobs in reserving phases across every
project. `runtime_connected=true` now means that count is backed by the integration.
Direct unlinked runs have no organizational identity and are not attributed to one.
Neither starting nor finishing changes persisted AI availability. Lowering a
concurrency limit does not cancel existing runs; it blocks new starts until count
is below the new limit.

Start takes the workspace lock, reads fresh identity/membership/dependency/runtime
state, then creates the existing job, trace event, link, latest pointer and task
status in one transaction. Failure rolls back all of them. Competing cross-project
requests serialize under the same fence, and repeated clicks conflict instead of
creating another active run. Terminal checkpoints take that fence and synchronize
the board in the same transaction. Cancellation retains its slot until the worker
safely settles the execution; a cancellation request alone is not completion.

## Status, approval and human acceptance

| Action / outcome | EngineeringTask status |
| --- | --- |
| Explicit start from Backlog, Planned, In progress or unlinked Review | In progress |
| Coding plan awaits approval | In progress |
| Execution failure or cancellation | In progress, with visible recorded outcome |
| Successful development + passing tests + approved AI review | Review |
| Human accepts latest successful result | Done |
| Human requests changes | In progress, with a fresh linked run |

The coding approval hash is the existing engine receipt. The normal task UI shows
the plan and files with **Approve & continue**, and sends that receipt internally.
No source-code mutation precedes approval. Failed approval freshness checks follow
the existing behavior: cancel the stale run, wait for terminal settlement and retry
from a fresh repository snapshot.

Human acceptance checks task revision, latest execution identity, successful
engine evidence and unchanged reviewed artifact integrity using the existing
delivery receipt validation. It records accepted state/time and marks Done; it
does not call Git/GitHub delivery. Criteria remain unverified requirements because
the current engine cannot reliably map individual tests to individual criteria.

Manual status changes on linked tasks are refused so Done cannot bypass acceptance.
Unlinked human/manual tasks retain their existing board controls. Ownership and
membership changes that affect an active run are refused; use the existing Cancel
execution action and wait for settlement. Assignment history remains intact.

## Retry and requested changes

Failed/cancelled execution retry creates a new existing job, run UUID and isolated
workspace, linked to the same EngineeringTask and its current eligible owner.
Previous executions, snapshots, errors and review decisions are preserved.
The existing `/tasks/{id}/retry` endpoint recognizes linked jobs and routes through
the same eligibility/concurrency checks; only the latest stopped run can be retried.

Request changes records feedback on the reviewed run and creates a new linked run
atomically. It includes original task requirements, human feedback and bounded
previous-result explanation/diff context, clearly identified as context rather
than applied source. The new coding Planner re-inspects a fresh source snapshot,
and human coding-plan approval is required again. No old workspace is reused.
Feedback persists through subsequent failure/cancellation retries. Prior context
is capped at 2,000 explanation and 5,000 diff characters; total requests remain
within the existing 20,000-character execution limit.

## APIs and frontend

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/engineering-tasks/{id}/executions` | Start / fresh stopped-run retry with task revision |
| GET | `/engineering-tasks/{id}/execution` | Coherent task, eligibility, current job and history |
| GET | `/engineering-tasks/{id}/executions` | Historical links and canonical phases |
| POST | `/engineering-tasks/{id}/accept` | Accept latest result with task revision and execution task ID |
| POST | `/engineering-tasks/{id}/request-changes` | Same identifiers plus feedback; new run |

Existing `/tasks/{id}/approve`, `/cancel`, `/retry`, `/trace`, `/files`, `/delivery`
and `/archive` routes are reused. Task detail adds an AI execution section,
completed/unfinished prerequisites, runtime reservations, actual recorded timeline,
coding-plan review, safe result package, acceptance/feedback and execution history.
Changed files, diff, tests and AI findings come directly from persisted snapshots.
The Board polls persisted planning state for status synchronization. AI cards show
actual active/reserved runs independently of assigned ownership. Advanced details
open the existing Engineering/Results interfaces through shared navigation.

After acceptance, **Create commit**, **Apply locally** and **Create draft PR** use
the existing delivery confirmation UI and engine. Linked delivery is guarded on
the server until the latest result is accepted. No publication occurs automatically.

## Run the complete scenario

```powershell
.\scripts\frontend.ps1 build
.\scripts\run-platform.ps1 api
# Separate terminal:
.\scripts\run-platform.ps1 worker
```

Ensure the currently configured local Ollama model is running. Docker is needed
for container tests; Python trusted-local tests remain an explicit approval option.

1. Register the actual repository in Projects and create a product plan.
2. Create a workspace AI member: active, developer role, available, matching skills,
   maximum concurrent executions 1. Join the project's squad.
3. Assign the EngineeringTask. Finish its dependencies; assignment starts nothing.
4. Open the task and choose **Run with CodeOps**. It becomes In progress.
5. Inspect the generated coding plan, select test runner/framework/attempt budget,
   then **Approve & continue**. Code changes remain in the isolated workspace.
6. After success, inspect **Preview / Review**: diff, tests, AI review and timeline.
   The task is Review and the runtime slot is released. Failure stays In progress.
7. **Accept result** marks Done. Alternatively enter feedback and **Request changes**
   for another fresh approved run.
8. Choose delivery separately. Refresh or restart to confirm history persists.

No task is automatically dispatched when another releases its slot.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_task_execution_bridge.py
.\.venv\Scripts\python.exe -m pytest
# Disposable PostgreSQL database:
$env:ASE_INTEGRATION_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:PORT/DATABASE'
.\.venv\Scripts\python.exe -m pytest tests/test_task_execution_bridge.py tests/test_team_migration.py
```

Bridge tests run the actual Worker, approval boundary, snapshot editing, unittest
process and Reviewer/Supervisor with explicit deterministic test providers.
PostgreSQL bridge fixtures use isolated schemas. Coverage includes eligibility,
dependencies, administrative availability, queue/runtime separation, cross-project
and duplicate-click races, atomic rollback, cancellation, fresh retry, feedback,
human acceptance, artifact integrity gates, persistence and existing engine APIs.
Full-suite opt-ins also exercise real Docker, Node and PostgreSQL integrations.

## File manifest

Added under `src/autonomous_engineering/`: `application/execution_requests.py`,
`domain/task_executions.py`, `infrastructure/task_execution_tables.py`,
`infrastructure/task_execution_store.py`, `api/task_executions.py`.

Modified under that directory: `application/worker.py`, `domain/teams.py`,
`infrastructure/task_store.py`, `infrastructure/planning_store.py`,
`infrastructure/team_store.py`, `infrastructure/team_migrations.py`, `api/tasks.py`,
`api/planning.py`, `platform.py`.

Frontend additions: `TaskExecutionPanel.tsx`, `WorkbenchContext.ts`.
Frontend modifications: `App.tsx`, `Planning.tsx`, `TaskAssignmentEditor.tsx`,
`Teams.tsx`, `useWorkbench.ts`, `teamTypes.ts`, `product.css`.
Tests: added `tests/test_task_execution_bridge.py`; updated `tests/test_teams.py`
and `tests/test_workspace_resources.py`. Documentation: this guide,
`docs/teams-and-capacity.md`, `README.md`.

## Limits and next phase

The app remains a local workspace with coarse global write fencing and polling.
Coding quality depends on the configured model, tests and human review. Approval
waiting reserves a slot until continued or cancelled. Request changes regenerates
the implementation from fresh source with bounded prior-result context; it is not
an incremental branch continuation. There is no criterion-level evidence mapping,
automatic dispatcher, live hosted preview, organizational Tester/Reviewer mapping,
provider selector, accounts, automatic Git publication, merge or deployment.

The next phase should design stronger task acceptance evidence: associate real
checks with acceptance criteria and make unresolved requirements explicit, while
keeping human acceptance and delivery separate. It is not implemented here.
