# Local workflow monitor

The optional `autonomous_engineering.monitor:create_monitor_app` factory serves
a self-contained page and a live `POST /monitor/run` event stream. Run it from
the project root on `127.0.0.1:8765`, following the README command. It needs the
same virtual environment as the CLI; no Node installation or credentials are
needed.

The form accepts a repository path (relative to the server's working directory
or absolute) and an engineering request. Each invocation creates a new task and
retained, bounded text snapshot under the configured workspace root. The source
repository is read without modification. Existing Phase 4 exclusions and
inspection limits apply.

LangGraph custom events identify when actual nodes start. Its update stream
provides validated snapshots after nodes finish. The page renders observed
analysis, measured execution records, run identifiers, and the final stopping
point. Selecting a step reveals its execution record. An unexpected exception
produces a visible stream error; detailed diagnostics stay in the server log.

A valid draft plan is followed by `PLAN_APPROVAL_REQUIRED`.
Configure a local Ollama model using [Phase 5](phase-5.md) to enable
planning; otherwise the Planner reports `PLANNER_NOT_CONFIGURED`. The overall task remains failed under the existing domain contract;
the monitor describes this expected stopping point explicitly. The draft plan
shows proposed steps, risks, unexecuted test suggestions, and evidence provenance.
Phase 6 adds an explicit approval button and `POST /monitor/develop`, consuming
the exact plan/snapshot identity once. The Developer writes only approved paths
in that snapshot and returns an explanation, actual diff and measured duration.
The page shows those results. Source files remain unchanged; tests and review
have not run. See [Phase 6](phase-6.md) for limits and the small demo repository.

Replay uses the completed run's captured events in browser memory. It is marked
as recorded playback and does not call the backend. Refreshing loses this trace;
there is no persistent history, database, background queue, or task-management
API. Planning replay never grants approval. Development results are not part of
the planning replay. Only one planning/development operation may run at a time
per monitor process; a new run invalidates its previous pending approval. This is a local
development view, separate from the future React dashboard.

The monitor accepts local hostnames and same-origin browser submissions. Keep
the documented loopback binding. The ordinary `main:create_app` factory and
its health endpoint remain available independently on port 8000.
