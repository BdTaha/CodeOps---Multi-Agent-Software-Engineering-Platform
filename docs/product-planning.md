# Repository-grounded draft planning

Product planning proposes what to deliver; coding planning determines how to
implement one approved EngineeringTask. Both have separate human approval gates.

## Lifecycle and repository observations

`queued → generating → draft → approved`, or `failed` during generation.
The independent SQL worker retains its claim/heartbeat fence. ProductPlanningAgent
uses the configured Model Gateway and retries invalid output once with validation
feedback. Generation creates E/T draft refs only, never EngineeringTasks or CO
numbers. Drafts survive restart and stay out of Board, Teams and Engineering.
Older approved tasks remain visible when a new draft is generated.

The worker reuses RepositoryReader/RepositoryAnalyzer against registered source,
read-only. Inventory is bounded to 2,000 files / 20,000 entries / depth 32. It
prioritizes manifests and goal-relevant paths, sampling at most **40 UTF-8 files,
64 KiB per file and 256 KiB total**. Existing filters exclude links, VCS internals,
dependencies and build trees; planning also excludes `.env*` and paths containing
secret, credential, token or password names. Binary/oversized files are skipped.

Only derived observations reach the model: sampled paths/layout, detected
languages/frameworks, declared dependency names, testing structure, architecture
summary and limitations. Raw source, dependency values and host paths are omitted.
This is structural inspection, not verification of business capabilities, storage
behavior or tests. Filename filters cannot identify all hardcoded secrets, but
raw source is not sent in this planning phase.

Durable `planning_basis` records `repository_grounded`, analysis, inspected files
and limitations. Missing/unregistered/unsupported roots yield `goal_only` plus a
reason, without invented facts. Inventory/access/limit errors and unexpected bugs
fail visibly instead of silently falling back. Provenance is inspection-time
evidence; source changes require a new goal for fresh product observations.
Execution performs its own snapshot analysis before coding approval.

## Editing and authoritative validation

Edit plan title/summary/assumptions, epic title/description, and task title,
description, priority, estimate, area, epic, dependencies and criteria. Add/delete
or move tasks; add/delete epics. Deletion removes dangling dependencies; deleting
an epic deletes its tasks. Save before approval. Dependency selection supports
Ctrl/Cmd for multiple choices. Invalid intermediate browser edits are recoverable.

The backend validates the entire graph: unique E/T refs, existing epic membership,
nonempty epics, valid unique dependencies, no self-dependency/cycles, nonempty
criteria, finite estimates >0 and ≤24h, allowed priorities/areas, 1–8 epics and
1–32 tasks. Invalid Save returns 422 without persisting anything. Estimates are
rough engineering effort, not guaranteed delivery time.

Save includes the expected revision and increments it. Stale edits/approval
return **409**; Reload saved draft is explicit. Draft polling does not overwrite
unsaved edits. Approval binds the exact persisted revision, not a browser copy.

## Storage and atomic approval

Additive draft tables: `product_plan_drafts`, `product_plan_draft_epics`,
`product_plan_draft_tasks`, `product_plan_draft_dependencies`,
`product_plan_draft_criteria`, `product_plan_draft_versions`. Ordered epics and task
scalar fields are separate from normalized dependencies/criteria; immutable
revision snapshots preserve editing history alongside provenance.

**Approve Plan & Create Work Items** takes the existing workspace/project write
fence, rereads the goal, checks draft state/revision, revalidates saved content,
allocates project-local CO numbers, inserts permanent epics/tasks/dependencies/
criteria, and records timestamp and T→CO mapping in one transaction. SQLite and
PostgreSQL use the existing transactional locks. Failure rolls everything back;
concurrent/repeated approval cannot duplicate tasks or consume numbers. Initial
status is Backlog. Approval neither assigns nor starts execution.

Approved draft/provenance are immutable history; normal task status/assignment
changes remain available. Different planned work requires a new goal/draft.
Tables initialize within the existing startup migration fence, including already
migrated databases, without resetting any data. Legacy `ready` goals are read as
approved and marked `legacy_approved`; existing SQL statuses, task IDs, assignments
and history remain unchanged. Their provenance is unknown/goal-only, never
falsely grounded. Back up SQL storage and retained workspaces before upgrading,
and restart API/worker/preview services together.

## API

| Method | Route | Body / result |
| --- | --- | --- |
| POST | `/projects/{id}/plans` | `{goal}`; 202 queued record |
| GET | `/projects/{id}/plan` | Latest record, or null |
| GET | `/projects/{id}/plans` | Retained records, newest first |
| GET | `/product-plans/{id}` | Saved record/revision |
| PUT | `/product-plans/{id}/draft` | `{revision,draft}`; next revision |
| POST | `/product-plans/{id}/approve` | `{revision}`; approved record/mapping |
| GET | `/projects/{id}/engineering-tasks` | All approved tasks |

Writes preserve local-origin checks. Missing resources return 404, invalid drafts
422, stale/non-draft mutations 409. See [execution bridge](task-execution-bridge.md)
and [manual demo](v1-demo.md).
