# CodeOps verification

## Supplied logo — 2026-11-01

Replaced the sidebar mark with the user's original transparent cube-and-spark
artwork. A CSS alpha mask inherits the interface foreground; black and white
favicons match light and dark browser chrome. Both production builds passed.
The published sidebar mark and favicon declarations were verified in the browser;
its warning/error log was empty. The logo capture is `screenshots/logo-brand.jpg`.
Cloudflare version: `25f70c64-ebe7-487f-83fa-a49c8a5138e9`.

## Reference-led dark workbench — 2026-11-01

The user rejected the light/navy presentation and supplied a dark desktop-editor
reference. This revision restores dark mode and changes the working composition:
compact inline branding, flat repositories with a project context pane, separate
Planning input/draft panes, a task-context/artifact split, and a bottom execution
stage navigator. The prior visual stylesheet was replaced rather than retaining
the rejected light presentation as another layer.

- Frontend: **50 passed, 0 failed**. Both normal and showcase production builds
  passed after final CSS adjustments. TypeScript unused-code checks passed.
- Browser approval was explicitly renewed by the user. Visual review completed on
  the local showcase and the published Cloudflare version. The earlier browser
  approval failure recorded below no longer blocks this revision.
- Browser coverage: Projects, Planning, Board, Teams, Models, all nine Engineering
  tabs, command dialog/Escape, coding-plan approval controls, acceptance disabled
  until acknowledgment, and historical runs without acceptance actions.
- Responsive inspection: 390×844, 1366×768, 1440×900 and 1920×1080. No document
  horizontal overflow at the inspected phone/laptop/wide layouts; code, board
  lanes and the execution strip have bounded internal scrolling where necessary.
- Visual QA corrected stretched Teams skill chips and Board column sizing.
  Twelve screenshots were refreshed from actual loaded showcase screens.
- The published task/diff bookmark rendered the new layout and split diff;
  its browser warning/error log was empty. Deployment version:
  `216a74f9-260a-4f33-b99c-7c2f09c19b43` at
  [the TahaBd showcase](https://codeops-showcase.tahabd.workers.dev).
- No backend, transport, fixtures, domain state, model routing, approval, acceptance
  or delivery implementation changed. The execution strip consumes the existing
  selected-run stages and tab-navigation handler. The backend suite was not rerun
  for this presentation-only revision; previous results remain recorded below.

## Studio-workspace visual redesign — 2026-11-01 follow-up

The public showcase now uses the light canvas, navy sidebar and cobalt controls
documented in [the design system](design-system.md), replacing the earlier graphite
presentation. The Projects composition, shared navigation, Planning composer and
drafts, Board lanes, Teams, Engineering evidence and Models surfaces were restyled.
Existing saved sidebar choices remain valid; fresh desktop sessions start expanded.

- Frontend baseline and final: **50 passed, 0 failed** on each run.
- Both normal `/ui/` and root showcase production builds passed after the final
  source changes. `tsc --noEmit --noUnusedLocals --noUnusedParameters` passed.
- Wrangler asset dry run passed (the sandbox denied its optional log-file write);
  the authorized deployment outside that restriction completed successfully.
- Cloudflare version: `d9c33f19-171b-4e61-bab8-1eae8d347aa6`.
- Deployed root, current CSS asset and deep-link fallback returned HTTPS 200.
  The delivered stylesheet contains the light color scheme, navy navigation
  variables and new Projects composition. The CSP header remains present.
- Backend, workflow, transport, fixtures, evidence and delivery implementation were
  unchanged. The backend suite was not rerun for this presentation-only follow-up;
  its previous results are recorded below.
- **Browser visual verification is incomplete for this follow-up.** The first local
  preview could not connect through sandbox socket restrictions. A preview outside
  that restriction was started, but automatic browser approval then failed due to
  a usage-limit gate; a retry was also rejected. No alternative browser automation
  or gate bypass was used. Current screenshot files remain labeled as the previous
  presentation. Earlier browser coverage below applies to that earlier version.

## Presentation and isolated showcase — 2026-11-01

Status: deployed to [Cloudflare Workers Static Assets](https://codeops-showcase.tahabd.workers.dev) and manually verified on November 1, 2026.

- Baseline backend: **602 passed, 150 skipped**, 222.19 seconds. Final backend:
  **602 passed, 150 skipped**, 227.63 seconds. Skips are the existing explicit
  PostgreSQL, Docker, preview and Node integration opt-ins. Windows sandbox
  asyncio socket initialization stalled; the successful runs used the existing
  repository virtual environment outside that restriction, with fresh test temp
  directories. No application database or registered source was reset.
- Baseline frontend: **46 passed** and normal build passed. Final frontend:
  **50 passed**; frozen installation, normal `/ui/` build, separate root showcase
  build, TypeScript unused-code checks and Wrangler dry run passed.
- Added boundary tests exercise blocked network/destructive actions, draft-save
  revisions and explicit approval, retained approved-plan task separation,
  historical evidence isolation, per-visitor reset and unchanged HTTP forwarding.
- Backend source, workflows, persistence, API routes, tests, containers and service
  scripts have no changes in this phase. The three frontend API clients forward
  through a default same-origin transport; normal request semantics are retained.
- Browser checks covered Projects, Planning, Board, Teams, all nine Engineering
  tabs, model routing, preview configuration, command-search keyboard selection,
  draft save/approval, assignment without execution, explicit sample acceptance
  and read-only history. Actual captures are in `docs/screenshots`.
- Engineering layout was inspected at 1366×768, 1440×900, 1920×1080 and 2560×1440.
  No document horizontal overflow was found. Reduced-motion CSS and the spotlight
  preference guard were inspected; OS preference switching was not automated.
- The built showcase was also served with Wrangler's local Workers runtime.
  Root and unmatched deep navigation returned the same shell with HTTP 200;
  the CSP denied connections and iframes. A task/diff hash bookmark survived
  browser reload, with no warning/error console entries in that fresh built tab.
- Tracked files and 711 reachable historical objects were scanned for credential
  patterns; no matches were found. The source and generated showcase bundle had
  no matching secret patterns or personal absolute paths. The normal bundle
  contained no showcase fixtures. These checks are not an exhaustive secret audit.
- Public deployment succeeded after the operator authorized Workers access.
  Version `8f0390ad-532d-4d66-8a6e-5e14f62b83b5` serves the frontend from
  `https://codeops-showcase.tahabd.workers.dev`. Every major screen and
  all nine Engineering tabs were checked on the live site. Current and historical
  bookmarks survived refresh; a fresh live browser tab had no warning/error logs.
  Root and unmatched deep navigation returned HTTP 200 with the same shell;
  deployed CSP and nosniff headers were verified.
- The account hostname was changed to the requested TahaBd branding. The new
  HTTPS address and a refreshed Engineering task bookmark were verified in the
  browser with no warning/error console entries. Application assets were unchanged.
- [GitHub CI](https://github.com/BdTaha/CodeOps---Multi-Agent-Software-Engineering-Platform/actions/runs/41260761167)
  passed both backend and frontend jobs for implementation commit `901ce52`.
  The optional main-branch deployment job was skipped because its account variable
  is not configured. OAuth deployment works; unattended CI deployment still needs
  the documented account variable and token secret. No credentials are committed.

## Nemotron 3.5 Super exact thinking profile — 2026-10-20

Added `nvidia/nemotron-3.5-super-vl-120b-a12b` to the existing exact-model boolean
thinking profiles. For structured CodeOps requests, Provider default resolves to
Disabled; Disabled sends `chat_template_kwargs.enable_thinking=false`, and Enabled
sends true. Low/Medium/High are rejected by this CodeOps profile before transport,
and no Nemotron request sends `reasoning_effort`. No substring matching or gateway
redesign was introduced. Models uses the Nemotron compatibility-default label and
the shared Enabled selector now covers both Laguna and Nemotron.

Deterministic fake-transport tests cover all three supported policies, rejection
of all effort policies without fallback, unrecognized lookalike model IDs, and
the selected-model probe with default and Enabled policies. The probe retains its
fixed tiny JSON prompt, 32 output tokens, 25-second timeout, no repository content,
and no fallback. Tests also reject truncated or reasoning-only responses while
keeping reasoning content out of returned metadata. Existing Laguna/Kimi/GPT-OSS,
other protocol, credential/endpoint, and fallback regressions remain in the suite.

The earlier live probe was reported as provider_default with an incomplete result
at about 781 ms. No cause is asserted and no live NVIDIA generation/latency claim
is made: verification uses fixtures and disposable test databases, not cloud keys
or the working database. Token budgets, final-content/finish-reason validation,
timeouts, credential encryption, SSRF/DNS checks, and fallback rules are unchanged.

Focused NVIDIA/settings/gateway checks: **149 passed, 29 skipped**, 13.56s.
Skips are explicit PostgreSQL opt-ins; no live NVIDIA key is needed. Full backend:
**602 passed, 150 skipped**, 129.07s; skips are optional PostgreSQL/Docker/preview/
Node integrations. Frontend: **46 passed**; TypeScript/Vite production build
passed, 1,808 modules, JS 451.32 kB (137.64 kB gzip), CSS 90.41 kB. No existing
database reset or live hosted generation was performed.

## NVIDIA optional thinking and bounded compatibility probe — 2026-10-16

The operator reported a tiny Laguna Playground JSON request returning in roughly
7.8 seconds with reasoning off, while larger CodeOps requests without a thinking
control repeatedly hit the configured 600-second timeout. Different prompts and
conditions prevent attributing the delay solely to reasoning. No live cloud
generation or latency benchmark is claimed for this fix.

Exact documented model profiles now apply Laguna's
`chat_template_kwargs.enable_thinking=false` default for structured requests and
retain Kimi's legacy `reasoning_effort=low`. Explicit NVIDIA connection policies
are validated against documented support, without substring matching or sending
both controls. An Enabled option uses Laguna's documented boolean true; no effort
levels are invented for Laguna. Kimi Medium is rejected because its API documents
low/high/max; GPT-OSS 20B/120B supplies documented low/medium/high coverage.
Other protocols retain their existing payload behavior.

Saved JSON profiles accept missing reasoning fields through a backward-compatible
default. Credential encryption, endpoint validation, pinned DNS/SSRF checks, and
availability-only fallback remain unchanged. Explicit operator timeouts are not
modified; Models shows the effective value. Effective reasoning labels join safe
invocation metadata without prompts, provider output, or reasoning content.

The optional selected-model probe makes exactly one tiny fixed-prompt request,
32 output tokens and 25-second timeout, with no repository content or fallback.
It returns separate success/timeout/rejection/invalid-response status and safe
metrics; a successful catalog or probe does not prove engineering-task quality.
Tests use deterministic fake HTTP transports and disposable databases, not live
NVIDIA/Ollama keys or the working database.

Focused provider/settings/gateway suite: **137 passed, 25 skipped**, 11.48s.
Skips are explicit PostgreSQL opt-ins. Regressions cover exact request bodies,
unsupported policies, Kimi compatibility, encrypted persistence and legacy rows,
other protocol boundaries, safe bounded generation tests, local origin/revision
checks, effective timeout/status, and one-time timeout fallback without semantic
fallback. Frontend: **45 passed**, production build passed (1,808 modules,
JS 451.13 kB, 137.51 kB gzip). Full backend: **590 passed, 146 skipped**, 135.97s;
skips are opt-in PostgreSQL/Docker/preview/Node integrations. The existing full
suite also exercises semantic invalid-output failures without provider fallback.

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
