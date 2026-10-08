# Engineering Workspace

CodeOps uses persisted tasks and real execution evidence. Engineering work has a
single task-centered split-pane workspace; it does not run an illustrative replay.

## Navigation and routes

- **WORKSPACE:** Projects, Planning, Board, Teams.
- **ENGINEERING:** Workspace. All, Active, Review, Done, and History are navigator modes.
- **SYSTEM:** Models.

Engineering routes use URL hashes, so refreshing a bookmark preserves the selected
work: `#/engineering/task/<task-id>/<tab>` for current work,
`#/engineering/task/<task-id>/<tab>?run=<execution-task-id>` for historical work,
and `#/engineering/run/<execution-task-id>/<tab>` for standalone requests.
`#/engineering` restores useful work instead of opening a landing page. Legacy
`#/engineering/reviews` and `#/engineering/history` resolve into the same shell.
Navigator mode is retained as `?mode=reviews` (or active/done/history); explicit
read-only history selections add `inspect=1`. This also locks the current run when
opened from History, without requiring a second backend workflow.
Board and Teams task details link into this workspace.

The compact task header presents ownership, repository, run, status, next action,
and available controls. Nine stable tabs share the same selected task: **Overview,
Plan, Files, Diff, Tests, Review, Acceptance, Preview, History**. The secondary pane
contains the workflow rail or the tab's file, plan, test, finding, or run navigator.
The task browser owns all task discovery; the main pane only shows selected work.
Back to tasks switches the secondary pane to search, project/status filters, and
task/run rows while retaining the main content. Selecting a row switches it to
workflow, changed files, plan/tests/findings, and execution attempts. Review mode
contains tasks awaiting human review. Empty filters show a compact message and
Show all work; they retain the selected task. History loads existing per-task run
links in bounded groups and shows standalone legacy runs too.

The secondary pane is 240–260px on desktop. The global sidebar defaults to a
60px icon rail in every section. An arrow at its top expands or collapses it; the
choice persists locally across navigation and reloads, including Board. Existing
Engineering sidebar preferences are retained. Planning and Teams retain their own layout.
Arrow keys, Home, and End navigate the accessible tabs.

Code Review's diff and findings now live in Diff and Review. Results' reports,
tests, acceptance, and explicit delivery live within the task. Metrics and operation
timelines live in History. The obsolete Workspace, Review, Results, and Dashboard
page components have been removed. `src/engineering/` contains route/session hooks,
workspace chrome, diff parsing/rendering, approval, evidence, review dialogs, and
history views. Existing backend approval, review, acceptance, delivery, and preview
operations remain authoritative.

## Lifecycle-aware workspace

The frontend derives UNASSIGNED, READY, BLOCKED, RUNNING_ANALYSIS,
AWAITING_PLAN_APPROVAL, RUNNING_IMPLEMENTATION, REVIEW, DONE, FAILED, and
HISTORICAL from existing assignment, backend eligibility, job phase/node,
recorded operations, task status, and human review state. It does not persist a
second lifecycle model. Eligibility remains the authority for starting/retrying;
acceptance and accepted-delivery controls retain their existing server gates.

| Tab | Availability |
|---|---|
| Overview | Always enabled |
| Plan | Enabled with a plan; compact pending context during analysis/planning; attention during approval |
| Files / Diff | Enabled only with recorded changes; automatically selects the first change |
| Tests | Enabled with results; compact context once test execution starts |
| Review | Enabled with results; compact context once reviewer execution starts |
| Acceptance | Always enabled; neutral requirements before the first execution, existing evidence semantics afterward |
| Preview | Linked, successful, human-reviewable or accepted execution; useful configuration explanation if no profile; historical inspection remains read-only |
| History | Enabled once a job or retained run exists |

All nine tabs remain visible. Disabled tabs use muted styling, `aria-disabled`,
and short explanations. Clicks cannot navigate to them; arrow keys, Home, and End
skip unavailable tabs. An unavailable bookmark or stored tab falls back to
Overview, or Plan during plan approval. A valid explicit tab wins, including
historical evidence links. With no explicit choice, Overview is the default and
Plan is preferred at approval. Polling does not move users away from valid tabs.

The header emphasizes one next action: assign, run, review plan, view execution,
accept, explicit delivery, or eligible retry. Delivery promotes the first action
without a saved receipt (configured draft PR, then commit export, then local
application). Historical headers omit all mutation actions.

Before execution, Overview shows description, neutral requirements, dependencies
with actual statuses, owner/squad/runtime context, and execution readiness. The
secondary pane becomes a compact task inspector with owner context, dependencies,
criteria count and not-started execution, without repeated CTAs. Header and the
contextual Overview assignment button focus the existing TaskAssignmentEditor.
Engineering filters new choices/recommendations to AI developer identities; Teams
retains its existing general assignment behavior. Existing memberships,
deterministic recommendations, capacity warnings, revisions, and assignment APIs
are reused. Saving stays on Overview and refreshes readiness. Runtime/queue values
are shown only when reported. Dependency, inactive/offline identity, membership,
and capacity reasons remain visible; blocked tasks cannot start.

Running Overview shows current operation, owner, snapshot context and the latest
recorded operation result. It only displays artifact summaries already recorded.
Review surfaces implementation, tests, review, acceptance and preview evidence.
Done shows acceptance and delivery receipts; failed/cancelled work shows the
recorded error, last successful operation, readiness and history. Once execution
exists, the secondary pane returns to the existing workflow model and adds file
navigation only when changes exist. Navigator rows show known blockers or recorded
progress; inventory data alone never claims authoritative execution eligibility.

## Inspecting and acting

The diff navigator shows real added/modified/deleted files. Unified and split views
preserve recorded line numbers and hunks, align replacement blocks, color additions
and deletions, and support copying paths, downloading the diff, and collapsing files.
Prism highlights the selected Python, JavaScript, TypeScript, JSX/TSX, Java, C/C++,
JSON, YAML, HTML, CSS, shell, and Markdown grammars locally. Tokens render as React
text spans, never injected HTML; unknown or oversized inputs remain plain text.
Whitespace, line numbering, and addition/deletion backgrounds are preserved.
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

Automatic selection restores a valid previous task, then chooses a genuinely
executing task, a task in review, planned/assigned work, or the first available task.
If no tasks exist it uses a retained standalone run; only an empty inventory shows
the small no-work state. Current selection is stored in both the URL and local
browser storage. Explicit task/run bookmarks are never replaced by auto-selection.

The backend records operation completion, not individual plan-step completion.
Diff context is limited to retained hunks; unrecorded context cannot be reconstructed.
Large selected diffs render 500 rows initially and load more on request. Diff
highlighting operates per line, so multiline token context outside a retained hunk
can be incomplete; full source highlighting retains multiline token boundaries. Snapshot
source availability depends on retained workspace files. Standalone runs have no
EngineeringTask ownership or managed preview. Compact HTTP projections reduce
payloads, but database hydration is unchanged. Real current production tasks did not
have linked historical runs. Lifecycle interaction, contextual assignment, and historical
inspection were additionally verified using isolated UI fixtures of the real workspace
with test-only API responses; production tasks were not changed.

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
states, historical evidence separation, semantic tabs, selection priority, navigator
empty states, read-only history selection, syntax text/line/escaping integrity, lifecycle
phases, tab availability, saved/deep-link fallback, neutral requirements, assignment/run
actions, dependency/offline blockers, first-file selection, human review, and accepted delivery. Backend projection tests
check that compact responses preserve counts and default API contracts without
mutating retained artifacts. Optional integration suites require their configured
Docker/PostgreSQL/provider environments.

## v1 planning and Engineering polish

Planning shows provenance, editable E/T draft refs and explicit Save/Approve actions.
Saved plan history retains immutable approved records. Board lists all approved
tasks while another goal is drafted. See [planning](product-planning.md).

Before execution, the header owns the dominant assignment/run CTA. The compact
sidebar shows task/owner/dependencies/criteria/execution context without repeating
buttons. Overview owns detailed readiness; assignment and dependencies are separate
conditions. One contextual assignment CTA is retained there. Running, approval,
review, done and historical tab behavior are unchanged.
