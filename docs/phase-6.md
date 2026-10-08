> Historical milestone: current v1 architecture and behavior are documented in
> [architecture](architecture.md), [README](../README.md) and [demo](v1-demo.md).

# Phase 6: Developer Agent

The Developer turns an explicitly approved plan into real text edits in the
managed snapshot. Local Ollama generates structured complete file replacements;
trusted Python validates the entire proposal before applying any edits. The
source repository is never the write target. No generated commands are run.

## Structure and decisions

```text
src/autonomous_engineering/
  agents/developer.py                  # Context, approval identity, scoped generation
  domain/development.py                # Validated full-file proposal contracts
  tools/workspace_changes.py           # Path checks, edit validation, diff and rollback
  infrastructure/ollama.py             # Shared bounded local structured transport
  infrastructure/ollama_developer.py   # Developer schema and prompt
  workflows/development.py             # Two-node approved LangGraph continuation
  domain/results.py                    # Development artifact with diff and approval receipt
  workflows/state.py                   # Artifact consistency and downstream invalidation
  monitor.py                          # In-memory pending plan and single-use approval endpoint
  monitor.html                        # Review, approval, explanation, real diff and durations
tests/test_developer.py                # Scope, invalidation, rollback and monitor integration
```

An approval ID is a SHA-256 digest over the task, run, managed workspace path,
complete plan, inventory and each eligible snapshot file's content. The local
monitor retains the validated **running snapshot immediately after planning**,
before its planning-only report. The ordinary CLI still ends at
`PLAN_APPROVAL_REQUIRED`; terminal snapshots are never reopened. A separate
finite LangGraph continuation runs `develop_implementation` then
`finalize_development` on the retained running snapshot.

Approval requires an explicit monitor POST; model output cannot approve itself.
The approval is consumed once before inference, checked before generation and
again before writes. Starting another run discards the previous pending approval.
Artifacts contain the consumed approval ID and UTC acceptance time. Replacing
analysis, plan or changes invalidates the development artifact in workflow state.
These are local integrity checks, not user authentication or durable audit logs.
Restarting the monitor loses pending approvals. Persistence arrives in Phase 10.

The provider receives only the task text, approved plan, and complete approved
files. The original host repository path is omitted from the Ollama request.
Source and model output are treated as untrusted evidence. Paths are restricted
to those in the approved plan; no model-selected extra files or commands are
accepted. A typed `DevelopmentProvider` protocol allows injection without tying
the agent to Ollama. Both LLM adapters share the existing local-only, proxy-free,
no-redirect, bounded JSON-schema transport.

## Limits and writes

- 1–8 distinct, case-insensitively unique plan paths; at most eight edits.
- Full files only: maximum 32,000 characters per file, 24,000 total input
  characters. Large contexts fail instead of supplying truncated files.
- At most 32,000 characters per generated file and 128,000 UTF-8 output bytes
  across edits. Ollama's output token budget can impose a smaller practical limit.
- Create, modify and delete kinds must match observed existence. Duplicate,
  out-of-plan, unchanged, malformed or binary edits are rejected before writes.
- Relative confinement, excluded credentials/directories, symlinks, junctions,
  Windows device names, and trailing dot/space aliases are denied.
- Root must be exactly the configured managed storage plus this run's UUID.
  Existing link components in its parent chain are refused.
- All edits are validated before application. Ordinary I/O failures trigger
  rollback of file contents. If rollback itself fails, a distinct error tells
  the user to inspect the retained snapshot. Empty directories may remain.

This is a bounded local prototype, not an OS sandbox or crash-atomic filesystem
transaction. Concurrent hostile filesystem replacement and process crashes are
not covered. Snapshots omit binary, oversized, credential, dependency and Git
metadata files; they are not complete Git checkouts. The diff is a review artifact
for the actual text changes. The snapshot files are the concrete resulting code.
Export/apply to the original repository and Git integration are future work.

## Run and visualize

Keep the existing local Ollama configuration from [Phase 5](phase-5.md). Start:

```powershell
.\.venv\Scripts\python.exe -m uvicorn autonomous_engineering.monitor:create_monitor_app --factory --host 127.0.0.1 --port 8765
```

1. Open <http://127.0.0.1:8765/> and run an engineering request against a repository.
2. Read the generated plan, especially proposed file paths and limitations.
3. Click **Approve this plan & develop snapshot** only after reviewing that plan.
4. Inspect the explanation, changed paths, unified diff, measured Developer
   duration, and retained workspace path. Local inference can take several minutes.

Planning replay contains only the recorded planning events; development results
remain in the current page until a new run or reload. Approval never occurs during
replay. The monitor has a single shared in-memory pending run, so use one local
session rather than concurrent users. It remains a development tool, separate
from the future task API and React dashboard.

The developer operation can succeed while the overall engineering task remains
`failed` with `TEST_AGENT_NOT_IMPLEMENTED`. This accurately reports that tests and
review have not run. Phase 7 adds real test execution; Phase 8 adds review.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_developer.py -W error
.\.venv\Scripts\python.exe -m pytest -W error
```

Tests use explicitly identified fixture providers and fixture approvals. They
verify actual file contents and source isolation, plan/task/run/content changes,
reserved and excluded paths, whole-proposal validation, mid-generation changes,
I/O rollback, full-file budgets, invalid provider results, artifact invalidation,
cross-origin rejection, single-use monitor approval, and real diff output. They
do not claim model-generated code is correct or has passed repository tests.
