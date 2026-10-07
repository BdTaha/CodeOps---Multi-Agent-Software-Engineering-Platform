# Teams, capacity and task assignment

This phase adds resource planning to the existing product planning layer. It does
not run the Developer, Tester or Reviewer agents. An EngineeringTask is planned
work, a TeamMember is an organizational resource, and an ExecutionRun is an actual
coding execution. Those concepts remain separate. `execution_run_id` remains
unchanged and nullable.

## Architecture

- `domain/teams.py` validates squads, member skills, capacity configuration,
  assignments and recommendation contracts. Human and AI members share identity,
  role, primary squad, active state and skills, but have distinct validated capacity
  fields. Member type is immutable; editing skills/capacity/primary squad is allowed.
- `infrastructure/team_tables.py` defines additive SQLAlchemy tables and a project
  revision fence. `PlanningStore` creates those tables beside the existing product
  tables. No existing table is replaced and no data backfill is needed.
- `infrastructure/team_store.py` persists resources and assignments, checks project
  ownership, computes snapshots, and applies decisions in transactions.
- `application/assignment_recommendations.py` is a pure deterministic service.
  It uses persisted planning data and never calls an LLM.
- `api/teams.py` exposes local-workspace endpoints with origin checks on writes.
- `Teams.tsx` manages squads, members, workload and unassigned work.
  `TaskAssignmentEditor.tsx` adds manual ownership and individual recommendations
  to task details. The Board shows owners and supports assignee/squad filters.

## SQL schema

| Table | Purpose and relationships |
| --- | --- |
| `team_squads` | Project FK, name, description, configured areas (JSON text), creation timestamp, revision |
| `team_members` | Project FK, primary squad FK, name, role, human/AI type, active state, human hours/utilization or AI availability/concurrency/future role, timestamp, revision |
| `team_member_skills` | Composite member FK + technical area primary key; manually configured proficiency 1–5 |
| `engineering_task_assignments` | Task FK primary key guarantees one owner record; squad FK, optional member FK, assignment timestamp |
| `team_project_revisions` | Project FK primary key and revision used to fence suggestions and serialize capacity checks |

Task responses expose nullable `squad_id` and `assignee_id` from the normalized
assignment table. Existing tasks start unassigned. Assignment and status changes
share the EngineeringTask revision, so a stale board/detail request returns 409.
Squad and member edits also require their current revisions.

A member's primary squad and assigned tasks' squads move together when the member
is edited. Human/AI types cannot be converted in place. Inactivation retains saved
ownership and load but excludes that member from recommendations.

SQLite and PostgreSQL use the same schema. A project-row SQL update serializes
assignment/load checks. Squad, member, assignment, task-status and new-plan changes
advance project revisions. Bulk application checks the proposed project revision,
each task revision, and combined capacity inside one transaction. Any failed
decision rolls back the whole batch. Suggestions are transient; saved assignments
and capacity configuration persist.

## Capacity

Human assignable capacity = weekly availability × target utilization (stored as
a fraction greater than zero and at most one). Reserved capacity is the difference.
Planned load sums estimated effort for all of that member's assigned tasks not Done,
including earlier plans. Remaining capacity is assignable capacity minus load and
can be negative after a manual override. Reassigning a task to its existing owner
does not count it twice. Done releases load; reopening restores it.

For example, 30h weekly availability at 80% target gives 24h assignable and 6h
reserved. A 17h saved load leaves 7h of planned capacity. These figures represent
planning budgets, never actual hours worked, a guaranteed week of delivery, or
employee performance.

AI members have manually configured `available`, `busy` or `offline` state and a
positive maximum planned task count. The UI defaults a new AI configuration to one
slot. Each assigned task not Done consumes a slot. Human weekly-hour fields are
rejected for AI members; AI capacity/role fields are rejected for humans. AI records
are organizational identities and do not change the runtime worker state.

## Explainable recommendations

Individual recommendations consider only active humans and active AI members marked
available, with an exact configured skill for the task's technical area. A squad-only
assignment restricts recommendations to that squad. General matches General rather
than silently standing in for every skill.

Candidates that fit capacity rank before candidates with a capacity warning. Within
each group the score is:

`10 × proficiency + 5 if squad covers the area + 5 × remaining capacity fraction`

The human fraction uses remaining/assignable hours, clamped to 0–1. The AI fraction
uses remaining/maximum slots. Stable member IDs resolve ties. Each candidate shows
its skill match, squad match, remaining hours or slots, and relevant warnings.

The batch service examines current-plan unassigned tasks in priority order, then
numeric task key. After each suggestion it updates a temporary projected load before
considering the next task. Batch suggestions require sufficient capacity and a
squad that covers the area; unmatched work is reported rather than forced onto
someone. Batch application rechecks eligibility and cumulative capacity atomically.

Unfinished dependencies appear as warnings with task keys. They are not assumed to
run in parallel. The service assigns ownership, not execution dates. Manual decisions
with capacity, availability, skill, squad or dependency warnings require the explicit
“Assign despite these warnings” action. Batch dependency warnings are shown in the
suggested plan before the explicit Apply action; batch capacity overruns are refused.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/projects/{id}/teams` | Squads, members, capacities, all project tasks and project revision |
| GET / POST | `/projects/{id}/squads` | List / create squad |
| PATCH | `/squads/{id}` | Edit complete squad configuration with revision |
| GET / POST | `/projects/{id}/members` | List members/capacities / create member |
| PATCH | `/members/{id}` | Edit complete member configuration with revision |
| POST | `/engineering-tasks/{id}/assignment` | Squad and/or member, task revision, optional explicit warning override |
| DELETE | `/engineering-tasks/{id}/assignment?revision=N` | Remove ownership with revision check |
| GET | `/engineering-tasks/{id}/recommendations` | Read-only individual suggestions |
| GET | `/projects/{id}/assignment-recommendations` | Read-only projected assignment plan |
| POST | `/projects/{id}/apply-assignment-recommendations` | Explicit selected decisions with project/task revisions |

Cross-project resource IDs return 404, invalid configuration returns 422, stale
decisions return 409, and cross-origin writes return 403. A manual warning response
has `detail.message` and `detail.warnings`; retrying requires `override_warnings=true`.
No resource creation endpoint seeds fake members, squads, assignments or activity.

## Run and use

From the project directory, build the frontend and start the usual services:

```powershell
.\scripts\frontend.ps1 build
.\scripts\run-platform.ps1 api
# Separate terminal, for existing goal planning and coding execution:
.\scripts\run-platform.ps1 worker
```

Open http://127.0.0.1:8765/ui/. Select your project and open Teams. Create a squad,
then add human members with weekly capacity/utilization/skills or AI members with
availability, planned slots and future execution role. Open a Board task to choose
a squad/assignee or inspect recommendations. Save and review any warnings. Teams
updates load from saved assignments. Refreshing retains all records.

“Recommend assignments” in Teams only creates suggestions. Review the explanations
and warnings, then use “Apply suggested assignments” to persist them. You can also
inspect assigned work under each member, open those tasks, change status, reassign
or remove ownership. Earlier-plan assignments remain visible there so their load
can be managed even when the Board shows a newer plan.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests/test_teams.py
# Optional disposable PostgreSQL database, using your own local connection URL:
$env:ASE_INTEGRATION_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:PORT/DATABASE'
.\.venv\Scripts\python.exe -m pytest tests/test_teams_postgresql.py
```

Tests cover SQL reopen, human reserve/load, AI slots and availability, Done release,
manual warning override, stale revisions, matching/ranking, inactive exclusion,
project isolation, squad/member edits, squad-only ownership, reassignment/removal,
read-only suggestions, atomic bulk application and competing capacity decisions.
The optional PostgreSQL test exercises real schema/persistence/application behavior.

## Limitations and next phase

- One primary squad per member and one primary assignee per task.
- No deletion UI; members can be inactivated. Resources are project-scoped, not
  workspace-wide shared identities.
- Capacity is a simple planning budget across outstanding work. There are no
  calendars, dates, sprints, timesheets or performance scores.
- Skills and AI availability are manually configured; there is no inference of
  human performance or automatic worker telemetry.
- Suggestions are a greedy, explainable heuristic rather than an optimal scheduler.
  Individual warnings can be overridden manually. Automatic suggestions stay within
  configured budgets, but their estimates remain rough.
- No EngineeringTask → ExecutionRun bridge, preview, authentication/permissions,
  provider switching, board-driven PR automation or deployment is introduced.

The next phase should design an explicit, user-triggered EngineeringTask →
ExecutionRun bridge for assigned AI developer identities, with traceability and
existing plan/review approval gates. It is deliberately not implemented here.

## File manifest for this phase

Added:

- `src/autonomous_engineering/domain/teams.py`
- `src/autonomous_engineering/infrastructure/team_tables.py`
- `src/autonomous_engineering/infrastructure/team_store.py`
- `src/autonomous_engineering/application/assignment_recommendations.py`
- `src/autonomous_engineering/api/teams.py`
- `frontend/src/Teams.tsx`
- `frontend/src/TaskAssignmentEditor.tsx`
- `frontend/src/teamApi.ts`
- `frontend/src/teamTypes.ts`
- `tests/test_teams.py`
- `tests/test_teams_postgresql.py`
- `docs/teams-and-capacity.md`

Modified:

- `src/autonomous_engineering/domain/product_planning.py`
- `src/autonomous_engineering/infrastructure/planning_store.py`
- `src/autonomous_engineering/platform.py`
- `frontend/src/App.tsx`
- `frontend/src/Planning.tsx`
- `frontend/src/product.css`
- `frontend/src/productApi.ts`
- `frontend/src/productTypes.ts`
- `frontend/src/types.ts`
- `frontend/src/useWorkbench.ts`
- `README.md`
