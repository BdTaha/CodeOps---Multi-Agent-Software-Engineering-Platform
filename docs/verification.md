# CodeOps v1 verification — 2026-10-08

## Failed repair evidence retention — 2026-10-16

The live v1 walkthrough exposed an audit bug: a development-attempt increment
cleared the last valid development artifact and its test/review evidence before
replacement code existed. A failed repair generation could leave changed-file
metadata and workspace files but lose the actual diff and failed test output.

Replacement is now atomic within the validated snapshot: attempt/error recording
alone retains the existing artifact and evidence. Accepting replacement changes
or a replacement development artifact invalidates stale downstream results.
Failed generation goes directly to failed finalization without rebuilding the
previous cumulative diff or rerunning tests/review over the retained evidence.
The existing no-change repair path still requests fresh validation. The UI labels
retained evidence as belonging to the last successfully produced code artifact,
explicitly distinguishing it from a successful run.

Deterministic regressions exercise initial multi-file development → actual
nonzero unittest execution → allowed repair → `INVALID_DEVELOPMENT` before a
replacement → final FAILED. They compare the retained artifact, diff, hashes,
original files, approval receipt, and complete failed TestResults with the earlier
recorded snapshots; verify separate test/repair errors; and check checkpoint/JSON,
SQLite reopen, full API retrieval, and retained file access. Another regression
checks rejected-review retention after failed repair. Successful replacement
clears Tests A before executing Tests B; existing no-change and bounded-repair
tests remain covered. Frontend rendering tests check actual diff hunks, command,
nonzero exit and output, separate History failures, available historical tabs,
and the retained-artifact notice rather than empty-state messages.

The optional Docker regression executes the actual offline container unittest
failure, then fails a deterministic repair provider and retrieves the failed
snapshot's diff/test output through the API from a disposable SQLite database.
No external inference keys are required. No working database or existing run
history is reset, repaired, or reconstructed. Already-discarded historical
artifacts are not fabricated or recovered by this change.

Developer instructions now cover existing API/helper exception contracts,
resource lifetimes, and isolated deterministic tests with temporary/configurable
storage. No Docker runner, approval, delivery, acceptance, or provider-fallback
policy was changed. The timeout default remains 180 seconds; explicit operator
overrides remain respected. See [timeout/fallback documentation](provider-settings.md#request-timeout-and-fallback-latency).

Completed targeted checks (the older release results in the following sections
describe the October 8 baseline):

* Final normal backend suite: **555 passed, 139 skipped**, 245.76s. Optional
  PostgreSQL/Docker/preview/Node integrations remain opt-in; Docker checks below
  were run separately. An older graph test encoded attempt-count invalidation;
  it now explicitly checks both retention and replacement semantics.
* Focused retention/state/durable/reviewer suite: **79 passed, 7 skipped**, 32.51s.
  Skips are optional Docker/PostgreSQL/Node integrations.
* Graph update semantics: **20 passed**, 3.53s, including both attempt-only retention
  and real replacement invalidation.
* Actual Docker failed-test/failed-repair/API retention: **1 passed, 5 deselected**,
  5.47s, with deterministic model providers and actual container unittest failure.
* Existing Docker non-root/read-only/network isolation check: **1 passed,
  11 deselected**, 6.85s.
* Frontend: **44 passed**; production TypeScript/Vite build passed, 1,807 modules,
  JS 448.17 kB (136.61 kB gzip), CSS 90.41 kB. No new UI empty-state failure.

## Release checks

* Normal backend: **549 passed, 138 skipped**, 167.90s. Skips are explicit PostgreSQL,
  Docker/preview/Node integration opt-ins; no required test failed.
* Frontend: **43 passed**, including draft fields/provenance/deletion and Engineering
  CTA/readiness/lifecycle checks. Frozen pnpm install passed.
* Production TypeScript/Vite build passed: 1,807 modules, JS 447.40 kB (136.36 kB
  gzip), CSS 89.90 kB. Node 22.18.0, pnpm 11.25.0, Python 3.12 locally.
* Focused draft/planning on SQLite plus disposable PostgreSQL: **88 passed**, 40.83s.
* Broader optional SQL/Docker verification: **206 passed, 1 skipped**, 364.89s:
  planning drafts/approval, execution bridge, real Python/Node preview
  health/isolation/network/cleanup, real Vite/FastAPI previews, Docker Python runners,
  persistent storage, migration fences and export boundaries. The skip is the
  separate Node runner opt-in, not Node preview coverage. It was then run explicitly
  with ase-node-runner:local: **1 passed, 11 deselected**, 3.97s.
* Registration backend journey with real Docker preview: passed within the separate
  preview run (**48 passed, 24 skipped**, 102.15s). This uses deterministic model
  fixtures but real HTTP/SQL/worker/filesystem/unittest/Git and Docker runtime.
  Registration returned HTTP 201, one Request Changes cycle created a new approved
  run, human acceptance marked Done, explicit commit ZIP existed, source stayed unchanged.
* CI YAML parses with required backend/frontend jobs, no continue-on-error and no
  provider/preview secrets. Commands match locally exercised install/test/build.

## Migration and actual UI checks

A SQLite backup was retained before restarting local services. All existing
**26 EngineeringTasks, 7 execution records, 2 legacy goals** survived additive
initialization; six draft tables were added. API/worker/preview were restarted
without resetting any existing data. Legacy ready plans display Approved/legacy
with unknown provenance, not fabricated repository inspection.

The actual browser shows the polished CO-15 header action, compact sidebar without
assignment buttons, separate assignment/dependency readiness in Overview, and
unchanged disabled pre-run tabs. A separate developer-demo-v1 source was registered.
Live **qwen2.5-coder:3b** generated a Repository-grounded draft in one attempt,
with six inspected files. It hallucinated Flask/password assumptions despite the
bounded observed context; those were corrected in the real editor before approval.
Estimate and criteria changes saved revision 1. The backend returned zero Board
tasks before approval. Explicit browser approval mapped T1→CO-1; the approved
Board task became assignable to Backend Agent / Backend Squad. The model-quality
issue demonstrates why grounding is evidence and human review remains essential.
The real coding planner then invented app/registration.py and app/app.py instead of
root files. That plan was cancelled before coding approval; no generated source
edits were authorized. The installed 3b model has not independently completed the
live registration journey. The complete deterministic backend journey does pass.

## Evidence boundaries

Automated E2E model responses are explicit fixtures, not a claim that an external
model independently completed every step. Tests/evidence do not guarantee production
correctness. GitHub draft-PR contracts are covered by transport tests; registration
journey delivery uses an actual local commit export, not a fabricated GitHub PR.
See [manual demo](v1-demo.md) for live model execution and recovery steps.

---

## Historical verification records

### Verified on 2026-10-06

The complete suite passed with **266 tests**, including opt-in integrations enabled.
The React TypeScript production build passed.

Verified on this Windows machine with Docker Desktop's Linux engine:

* Real unittest, pytest and dependency-free npm execution in runner containers.
* Unprivileged container identity, denied writes to source/root, denied outbound
  network connection and bounded termination of a long-running test.
* Real PostgreSQL task creation, transactional job claim and retained snapshots.
* SQLite reopen/history, cancellation, fenced ownership, interrupted-job recovery
  and preservation of a terminal checkpoint after lease expiry.
* A failed fixture repaired using actual unittest output, cumulative baseline diff,
  and stopping a still-failing fixture at the configured attempt budget.
* Independent worker completion, task/result/source APIs and origin/path checks.
* Real Git baseline/change commits, ZIP export and refusing newer source edits.
* GitHub adapter request contracts with mocked transport: full base tree preservation,
  draft PR request, deleted files and refusal when the base branch moves.

A live UI run used `qwen2.5-coder:3b` to plan and implement the greeting demo,
ran two existing tests in Docker, received model review approval and created a real
independent Git commit export. Browser refresh retained its approval checkpoint.
The original source remained unchanged.

A separate real-model benchmark passed three tests including a previously failing
whitespace behavior assertion, in one development attempt. Its observed Ollama
token telemetry was 3,794 input and 359 output tokens. This narrow result does not
establish general model quality. Full evidence is in local `benchmark-results.json`.

GitHub publication has **not** been performed against a real account: no token is
configured. Local source application was tested on disposable fixtures; the user's
repositories were not overwritten. The current dashboard uses SQLite; PostgreSQL
is running and verified as an optional configured storage backend.

The release is a local single-operator application, not a hardened multi-user service.
See [the runbook](platform.md) for remaining deployment boundaries and recovery policy.
