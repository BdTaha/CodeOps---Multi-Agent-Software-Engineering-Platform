# Frontend preview and live workspace

The roadmap was adjusted at the user's request: build the React/TypeScript
interface now so the product can be explored while the remaining agents arrive.
The four screens follow the supplied GitHub / coding workspace / observability
brief. This is the project frontend, separate from the earlier single-file monitor.

## Explore

Open <http://127.0.0.1:8765/ui/> while the local monitor server is running. The
interface starts in **Preview** mode. All example repositories, changes, timings,
test results and review decisions are labeled as illustrative data. Preview data
is never sent to a live provider and never approves a real plan.

- **Projects:** searchable repository cards, session activity, add a local path,
  and create an engineering task.
- **Agent workspace:** repository tree, selectable workflow graph, agent input,
  output, measured durations, attempt, structured errors and raw records. The
  example replay demonstrates a test failure and return to the Developer.
- **Code review:** changed-file navigation, highlighted unified or side-by-side
  hunks with line numbers, review comments when available, and diff download.
- **Results:** analysis/development summary, changed files, test/review evidence,
  measured operation time and the actual execution timeline.

Switch to **Live** or choose a local project, then create a task. Try
`examples/developer-demo` with the prefilled whitespace-trimming request. Ollama
must be running with the model already configured in `.env`. A run streams real
events, loads the snapshot file tree during planning, and stops for review.
Select **Planner** to inspect its plan. **Approve plan & develop** consumes the
same exact plan/snapshot approval as the existing monitor. Successful development
opens the real diff; opted-in unittest execution provides measured evidence, and passing tests trigger actual model review. The source repository is
not changed. Provider or file-access errors are shown explicitly.

GitHub connections, uploads, commits, pull requests, additional test framework adapters, durable task history and repair loops remain upcoming backend features.
Commit/PR controls are visibly disabled. Local repository registration is stored
in this browser; run results are held in this tab until refresh. Snapshot browsing
on the backend is limited to its latest run. Older session reports can be viewed,
but their source-file reader can return a clear stale-snapshot error.

## Build and run

From the project root in PowerShell, using installed Node/pnpm or the bundled
desktop runtime fallback:

```powershell
.\scripts\frontend.ps1 install
.\scripts\frontend.ps1 build
.\.venv\Scripts\python.exe -m uvicorn autonomous_engineering.monitor:create_monitor_app --factory --host 127.0.0.1 --port 8765
```

Build before starting the backend. The monitor mounts `frontend/dist` at `/ui`
when that directory exists. The legacy monitor remains at `/`. Restart the backend
if the build directory was first created after startup; subsequent rebuilds can
be loaded by refreshing the frontend.

For hot reload, leave the backend running and use a second terminal:

```powershell
.\scripts\frontend.ps1 dev
```

Open <http://127.0.0.1:5173/ui/>. Vite proxies `/monitor` and `/health` to the
local backend. It translates only the two exact frontend origins on port 5173;
other origins remain intact for the backend's same-origin rejection. The built
frontend uses the backend's own origin and needs no CORS exception.

On a machine with Node and pnpm already on PATH, the equivalent commands from
`frontend` are `pnpm install --frozen-lockfile`, `pnpm run build`, and `pnpm run dev`.
The PowerShell helper invokes the compiler and Vite directly, which also avoids
desktop runtime package-manager auto-install checks when building offline.
Vite's native compiler may need permission to traverse Windows project parent
directories in a restricted sandbox; normal user terminals do not have that
additional sandbox restriction.

## Structure

```text
frontend/
  package.json, pnpm-lock.yaml, pnpm-workspace.yaml
  index.html, vite.config.ts, tsconfig.json
  src/
    App.tsx              # Navigation, preview/live switch, task dialog
    Dashboard.tsx        # Projects and session activity
    Workspace.tsx        # File tree, workflow graph, source and agent details
    Review.tsx           # Diff hunks, file selection, comments
    Results.tsx          # Evidence-based report and execution timeline
    useWorkbench.ts      # Session state, streamed runs, approval and preview replay
    api.ts               # Typed backend requests and streamed-event parsing
    types.ts             # Frontend contracts and agent presentation metadata
    preview.ts           # Explicitly illustrative data, separate from live state
    components.tsx       # Shared status, tree and download helpers
    styles.css           # Dark, responsive layout and reduced-motion support
    main.tsx             # React entry point
scripts/frontend.ps1     # Install/build/dev helper with bundled runtime fallback
```

The backend adds two read-only local session endpoints for file inventory and
text content. They accept a known run UUID, derive its managed root server-side,
and reuse existing scoped readers. They never accept an arbitrary host repository
path. Traversal, excluded credentials, links and stale/unknown run IDs are rejected.
This remains a local development interface rather than the future authenticated
task-management API.

## Validation

The production build includes strict TypeScript checking. Backend tests exercise
the file reader, credential/traversal rejection and stale run access in addition
to existing agent/approval contracts:

```powershell
.\scripts\frontend.ps1 build
.\.venv\Scripts\python.exe -m pytest -W error
```

Browser verification covers navigation, agent selection, both diff views,
preview labels, real streaming, source browsing, and desktop/narrow layouts.
Preview counters are design examples, never backend test or evaluation results.

References: [React](https://react.dev/learn), [Vite 7](https://v7.vite.dev/guide/),
[pnpm build-script allowlist](https://pnpm.io/settings#allowbuilds).

## Real tests (Phase 7)

In Live mode, review a Planner result and select **Run unittest tests after development** before approving. This permits trusted repository code to execute on the local host. It defaults off. The Test Agent and Results screen show actual output and command exit status; unknown individual counts remain absent. See [Phase 7](phase-7.md).

## Review decisions (Phase 8)

After opted-in tests pass, the local Reviewer reads the real diff, current changed files, and test source/evidence. Its decision and recommended fixes appear in Agent details, Code review, and Results. The graph shows the actual active continuation node through `/monitor/activity`; timing and completed records come from the returned workflow state. Rejected review or provider failure stops the task. No repair loop runs yet. See [Phase 8](phase-8.md).
