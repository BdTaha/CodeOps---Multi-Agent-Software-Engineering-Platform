# Engineering Workspace

CodeOps uses persisted tasks and real execution evidence. Engineering work has a
single task-centered split-pane workspace; it does not run an illustrative replay.

## Navigation and routes

- **WORKSPACE:** Projects, Planning, Board, Teams.
- **ENGINEERING:** Workspace, Reviews, History.
- **SYSTEM:** Models.

Engineering routes use URL hashes, so refreshing a bookmark preserves the selected
work: `#/engineering/task/<task-id>/<tab>` for current work,
`#/engineering/task/<task-id>/<tab>?run=<execution-task-id>` for historical work,
and `#/engineering/run/<execution-task-id>/<tab>` for standalone requests.
Entry views are `#/engineering`, `#/engineering/reviews`, and `#/engineering/history`.
Board and Teams task details link into this workspace.

The persistent task header presents ownership, repository, run, status, next action,
and available controls. Nine stable tabs share the same selected task: **Overview,
Plan, Files, Diff, Tests, Review, Acceptance, Preview, History**. The secondary pane
contains the workflow rail or the tab's file, plan, test, finding, or run navigator.
It can be collapsed. Arrow keys, Home, and End navigate the accessible tabs.

Code Review's diff and findings now live in Diff and Review. Results' reports,
tests, acceptance, and explicit delivery live within the task. Metrics and operation
timelines live in History. The obsolete Workspace, Review, Results, and Dashboard
page components have been removed. `src/engineering/` contains route/session hooks,
workspace chrome, diff parsing/rendering, approval, evidence, review dialogs, and
history views. Existing backend approval, review, acceptance, delivery, and preview
operations remain authoritative.

## Inspecting and acting

The diff navigator shows real added/modified/deleted files. Unified and split views
preserve recorded line numbers and hunks, align replacement blocks, color additions
and deletions, and support copying paths, downloading the diff, and collapsing files.
Files reads the scoped execution snapshot without allowing edits. Findings navigate
to the affected diff or read-only source.

Plan approval appears within Plan. Pending plans do not imply completed development.
Eligible AI-owned tasks can start; active executions can be cancelled; successful
reviewable results can receive feedback or human acceptance. Acceptance retains
unresolved-evidence acknowledgment and preview cleanup. Accepted results expose
explicit commit, local apply, and configured GitHub draft PR delivery.

Historical selection is checked against the task's retained links. All views stay
on that selected run, label it as historical, and omit mutation controls. Historical
acceptance and human decisions are read from that run. Preview history is read-only.
Current preview controls preserve start, stop, restart, expiry, logs, and fallback
inspection through the other evidence tabs.

Teams uses horizontal resource rows with identity, role, availability, actual human
capacity or AI runtime/queue data, project membership, and squad active work.

## Loading and limitations

Compact optional API projections keep diffs, baseline files, and test logs out of
status polling. Existing endpoint defaults still return full records. Detailed
execution artifacts load on the first Files/Diff/Tests/Review visit and cache by run
revision. Polling stops for terminal work unless evidence is still being generated.
Inventory polling occurs while jobs are active; Refresh reloads settled data.

The backend records operation completion, not individual plan-step completion.
Diff context is limited to retained hunks; unrecorded context cannot be reconstructed.
Large selected diffs render 500 rows initially and load more on request. Snapshot
source availability depends on retained workspace files. Standalone runs have no
EngineeringTask ownership or managed preview. Compact HTTP projections reduce
payloads, but database hydration is unchanged. Real current production tasks did not
have linked historical runs, so history isolation was verified through unit tests
and the existing bridge suite rather than by changing users' tasks.

## Build, run, and verify

From the project root in PowerShell:

```powershell
.\scripts\frontend.ps1 build
.\scripts\run-platform.ps1 api
```

Open http://127.0.0.1:8765/ui/. For development use `scripts/frontend.ps1 dev`
with the API running. The UI is served from `frontend/dist`; refresh after rebuilding.

```powershell
cd frontend
npm test
npm run build
cd ..
.\.venv\Scripts\python.exe -m pytest tests/test_engineering_ux.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Frontend tests cover diff line numbers, replacement alignment, bookmarks, workflow
states, historical evidence separation, and semantic tabs. Backend projection tests
check that compact responses preserve counts and default API contracts without
mutating retained artifacts. Optional integration suites require their configured
Docker/PostgreSQL/provider environments.
