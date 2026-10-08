# Workspace teams and planning capacity

CodeOps saves product goals as editable drafts. Human approval creates permanent
epics and EngineeringTasks. Drafts are excluded from capacity/assignment queries;
all older approved work remains included. Teams assigns ownership
to those tasks. The autonomous coding system remains a separate execution layer;
assigning a task does not create an execution, start Ollama, or deliver a PR.
The [execution bridge](task-execution-bridge.md) now provides an explicit Run with
CodeOps action, coding-plan approval and final human result acceptance.

## Architecture

One local workspace owns `WorkspaceMember` identities and skills. A member can join
many projects through `ProjectMembership`, with one primary squad in each project.
Squads belong to projects. A task has at most one primary assignee and references
its project squad and workspace identity.

Identity editing changes name, role, skills, active state and human capacity or AI
availability/concurrency configuration everywhere. Membership editing changes only
the chosen project's squad and active state. Moving a membership also moves that
member's task assignments in that project; other projects remain unchanged.
Deactivation retains historical ownership and its outstanding workload. New
assignments require an active membership, even with warning override.

Normalized tables:

| Table | Purpose |
| --- | --- |
| `workspace_members` | Shared identity, revision and resource configuration |
| `workspace_member_skills` | Identity-level area/proficiency |
| `project_memberships` | Unique project/member relation, primary squad, active state, revision |
| `team_squads` | Project-specific squad and technical areas |
| `engineering_task_assignments` | Task, project squad, workspace assignee |
| `workspace_team_state` | Global decision revision and transactional write fence |
| `team_project_revisions` | Project decision revision |
| `team_schema_migrations` | Completed migration versions |

## Human capacity

```
assignable = weekly_capacity_hours * target_utilization
planned = sum(estimated_hours for all assigned tasks where status != done)
remaining = assignable - planned
reserved = weekly_capacity_hours - assignable
```

Load includes every project and earlier plans, including tasks owned by inactive
identities or memberships. Done releases planned effort. This is a budget for
outstanding work, without calendars or delivery dates; it is not tracked working
time or employee productivity.

For 30h weekly capacity and an 80% target, assignable capacity is 24h and reserved
capacity is 6h. Project A's 14h plus Project B's 7h produces 21h globally planned
and 3h remaining. A manual override can deliberately produce negative remaining
capacity; automatic recommendations stay within the configured budget.

## AI queue and runtime

`assigned_queue_depth` counts unfinished owned tasks across all projects. It is
planning information, and never consumes `max_concurrent_executions`.
An AI identity configured for one concurrent execution can own three or more
queued tasks. AI capacity has no weekly-hour budget.

`active_execution_count` now counts real linked runtime reservations and
`runtime_connected` is true for AI workspace identities. Queued planning, planning,
coding-plan approval waiting, queued development and development reserve slots.
Terminal runs and final human result review do not. The UI shows actual counts
and current runs. `max_concurrent_executions` controls explicit start, while
assignment ownership remains independent. See the bridge guide for precise states.

Manual assignments warn about inactive identities, busy/offline AI, missing skill,
squad area mismatch and unfinished dependencies. These warnings can be explicitly
overridden. No execution-slot warning is generated from queue depth.

## Recommendations and consistency

Candidates require an active workspace identity, active target-project membership,
matching skill and (for AI) available state. Busy/offline AI is excluded from
automatic suggestions. Squad-only ownership restricts candidates to that squad.

Score is proficiency * 10, plus 5 for squad area match, plus a balance bonus up to
5. Human balance uses remaining global capacity divided by assignable capacity,
clamped to 0..1. AI balance uses `5 / (1 + assigned_queue_depth)`. Queue balancing
cannot outweigh one proficiency level. Capacity-fitting candidates rank first;
stable identity IDs resolve ties. Reasons and warnings accompany each suggestion.

Batch recommendations project new assignments against the global task set. They
are read-only until explicit application. Application rechecks workspace revision,
project revision and each task revision, then commits all selected decisions or
none. Identity/membership/capacity/status/plan changes invalidate stale decisions.

Every planning-resource mutation first updates the same workspace state row, then
locks the project as needed. PostgreSQL row locks and SQLite's serialized writers
ensure a second project sees the first assignment's committed load before deciding.
Coherent reads use PostgreSQL repeatable-read or an explicit SQLite transaction.
This deliberately coarse workspace lock suits the current local app; very large
workspaces may later need per-resource locking and scoped snapshots.

## Existing database upgrade

Startup automatically runs the transactional `workspace-identities-v1` migration.
Back up your database before upgrading, and restart both API and worker so all
writers use the global fence. SQLite uses `BEGIN IMMEDIATE`; PostgreSQL uses a
transactional advisory lock while upgrading.

Each legacy `team_members` row becomes a workspace identity with the same ID,
configuration, revision and timestamps. Skills keep their member IDs. Each old
project/member relation becomes a deterministic membership. Existing squads, task
IDs, assignment values, plan history and execution history are preserved. The old
AI concurrency value is copied to `max_concurrent_executions`.

Assignment foreign keys are retargeted to workspace identities. PostgreSQL changes
the constraint in the transaction. SQLite copies and replaces only the assignment
table within the transaction. Legacy `team_members` and `team_member_skills`
tables remain intact as migration evidence; they are not used for future writes.
Failure rolls back and permits retry. A completed migration marker prevents
later startups from overwriting workspace edits with legacy rows.

Same-name identities are **not merged**. Short identity IDs distinguish them in
the workspace view and membership selector. Reuse one chosen identity in future
projects; there is no merge/reassignment wizard in this phase. Fresh databases
create only canonical team tables.

## API

All writes retain local-origin checks. Unknown resources return 404, invalid
configuration 422, and revision/membership/capacity conflicts 409. Manual warning
responses contain `detail.message` and `detail.warnings`; an informed retry uses
`override_warnings=true`.

| Method | Route | Meaning |
| --- | --- | --- |
| GET | `/workspace/teams` | Coherent identities/memberships/global capacities/tasks/projects snapshot |
| GET | `/workspace/members`, `/workspace/capacity` | Same coherent workspace snapshot |
| POST | `/workspace/members` | Create shared identity |
| PATCH | `/workspace/members/{id}` | Edit identity with revision |
| GET | `/workspace/members/{id}/capacity` | Global load and project breakdown |
| GET / POST | `/projects/{id}/memberships` | List / add existing identity to project |
| PATCH | `/project-memberships/{id}` | Edit squad/active state with revision |
| GET | `/projects/{id}/teams` | Project snapshot plus global capacity context |
| GET / POST | `/projects/{id}/squads` | List / create project squads |
| PATCH | `/squads/{id}` | Edit squad with revision |
| GET / POST | `/projects/{id}/members` | Compatibility list / atomic new identity and membership |
| PATCH | `/members/{id}` | Compatibility identity-only edit |
| POST / DELETE | `/engineering-tasks/{id}/assignment` | Save / remove explicit ownership with task revision |
| GET | `/engineering-tasks/{id}/recommendations` | Individual recommendations |
| GET | `/projects/{id}/assignment-recommendations` | Project proposal using global projected load |
| POST | `/projects/{id}/apply-assignment-recommendations` | Apply with workspace/project/task revisions |

Old create clients may send `max_concurrent_tasks` as an input alias; responses use
the canonical execution name. Clients must move squad editing to membership APIs
and include `workspace_revision` when applying recommendations.

## Run and test

```powershell
.\scripts\frontend.ps1 build
.\scripts\run-platform.ps1 api
# In a separate terminal:
.\scripts\run-platform.ps1 worker
```

Open http://127.0.0.1:8765/ui/ and select Teams → Workspace members. Create a human
or AI identity and skills once, even before registering projects. Select a project,
open Project teams, create a squad and choose Add existing member. Repeat in
another project with the same identity. Assign from Board task details or review
and explicitly apply suggestions. Workspace cards show global load, reserved
capacity, project breakdown and outstanding assigned tasks; AI cards show queue,
configured concurrency and real runtime reservations. Refresh preserves everything.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests/test_teams.py tests/test_workspace_resources.py tests/test_team_migration.py
# Use a disposable PostgreSQL database:
$env:ASE_INTEGRATION_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:PORT/DATABASE'
.\.venv\Scripts\python.exe -m pytest tests/test_workspace_resources.py tests/test_team_migration.py tests/test_teams_postgresql.py
```

Tests exercise shared identities, global loads and projected batches, real
cross-project contention, membership isolation, identity edits, availability,
soft queue balancing, unchanged concurrency semantics, legacy foreign keys and
duplicate names, idempotence, rollback/retry, freshness and existing planning.
PostgreSQL tests require explicit opt-in and use disposable fixtures.

## Files changed in this correction

Added: `infrastructure/team_migrations.py`, `tests/test_workspace_resources.py`,
`tests/test_team_migration.py`.

Modified under `src/autonomous_engineering/`: `domain/teams.py`, `api/teams.py`,
`application/assignment_recommendations.py`, `infrastructure/team_tables.py`,
`infrastructure/team_store.py`, `infrastructure/planning_store.py`.

Modified under `frontend/src/`: `App.tsx`, `Teams.tsx`, `TaskAssignmentEditor.tsx`,
`teamTypes.ts`, `teamApi.ts`, `product.css`. Also `tests/test_teams.py`,
`tests/test_teams_postgresql.py`, this guide and `README.md`.

## Limits and next phase

One local workspace, one primary squad per project membership, one primary task
assignee, manually configured skills/availability and greedy suggestions remain.
There are no dates, calendars, employee performance analytics, identity merge UI,
automatic dispatch or hosted previews. Existing autonomous engineering and
GitHub delivery continue through their existing workflow.

The explicit EngineeringTask execution bridge is now available; its architecture,
review gates, test instructions and next-phase limits are documented in
[task-execution-bridge.md](task-execution-bridge.md).
