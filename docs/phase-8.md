> Historical milestone: current v1 architecture and behavior are documented in
> [architecture](architecture.md), [README](../README.md) and [demo](v1-demo.md).

# Phase 8: Reviewer Agent

The approved continuation now follows development → tests → review → report.
Review is read-only and runs automatically only after real unittest execution
passes. Skipped/failed/error test outcomes stop before model review. Review
rejection and provider failures stop without repair; bounded retries are Phase 9.

## Structure

```text
agents/reviewer.py                    # Full-file context and review/reference validation
infrastructure/ollama_reviewer.py     # Local Ollama JSON-schema review adapter
domain/results.py                    # Review contracts and resulting-file hashes
workflows/development.py             # Conditional review operation and final status
monitor.py                           # Provider composition and actual node activity
frontend/src/Workspace.tsx            # Decision, findings, recommended fixes
frontend/src/Review.tsx               # File-specific comments and decision badge
frontend/src/Results.tsx              # Final evidence and truthful success/failure
tests/test_reviewer.py                # Evidence, stale decisions, provider and workflow checks
```

The agent depends on a `ReviewProvider` interface. The concrete provider uses the
same local-only, proxy-free, no-redirect, bounded JSON-schema transport as Planner
and Developer. No new LLM framework or service is needed. Repository text, diffs,
plans and test output remain untrusted evidence; they cannot instruct file edits
or commands. The Reviewer has no write or execution capability.

## Evidence and limits

The context includes the original request (without its host repository path),
approved plan, real unified diff, complete current changed files, complete
`tests/test*.py` source, and actual `TestResults`. Individual test counts are not
inferred. Unchanged application dependencies outside this context are not reviewed;
the report explicitly records the scope of model review.

Limits: eight changed files, twenty test files, 32,000 characters per source file,
24,000 source characters total, 48,000 diff characters, and six distinct findings.
Oversized evidence fails visibly rather than approving truncated source. Findings
must reference supplied paths and existing current source lines, with an exact excerpt of the referenced line. Deleted files
may be referenced without a line number, with an exact diff excerpt. Rejection must have actionable findings;
approval cannot contain unresolved high/critical findings.

Development records resulting-file SHA-256 hashes. Review checks changed files
against those hashes, and compares the managed snapshot fingerprint before and
after inference. Changed source or a stale decision is rejected. Older artifacts
without hashes require fresh development. These are local integrity checks, not
an OS sandbox, durable audit trail, or protection against hostile concurrency.
Trusted tests still run on the host under the Phase 7 execution choice. Model
review cannot guarantee correctness, security, or adequate coverage.

## Outcomes and UI

The graph records `review_changes` with measured duration and the actual decision.
Successful tests plus an approved review permit `task.status=succeeded` and a
matching report. A rejection records `REVIEW_REJECTED`; invalid output, stale
source, provider failure, and oversized evidence produce their actual error.
Missing test authorization keeps the task incomplete. Success applies only to
the snapshot: no original-source edits, commits, or PRs are performed.

Agent details and Results show severity, file/line, description and recommended
fix. Code review shows file-specific comments and the actual approval/rejection
badge. During the continuation, the UI polls the monitor's read-only, no-store
`/monitor/activity` endpoint for actual LangGraph node starts. Completed records
and measured durations arrive with the returned snapshot. This remains an
in-memory local monitor rather than a durable task API.

## Run and test

```powershell
.\scripts\frontend.ps1 build
.\.venv\Scripts\python.exe -m uvicorn autonomous_engineering.monitor:create_monitor_app --factory --host 127.0.0.1 --port 8765
.\.venv\Scripts\python.exe -m pytest tests/test_reviewer.py -W error
.\.venv\Scripts\python.exe -m pytest -W error
```

Restart the monitor for backend changes, then open <http://127.0.0.1:8765/ui/>.
In Live mode, submit a focused task, inspect the plan, select unittest execution
for a trusted repository, and approve development. After passing tests, the
Reviewer decides; inspect Results and Code review. A failed or rejected run needs
a new manually submitted task until Phase 9 implements bounded repair.

The demo's existing tests cover plain/empty greetings; they do not prove whitespace
handling. A Reviewer can legitimately request a targeted coverage test. Approving
a plan does not force it to approve the resulting implementation.

Tests use explicitly identified fixture providers and real fixture test processes.
They verify evidence/read-only behavior, malformed/contradictory decisions,
unsupported file/line references, stale source, context limits, local schema
transport, measured node ordering, rejected/error reports, success invariants,
and skipped review when tests do not pass. Fixture reviews are not runtime model
performance metrics.

## Observed local-model limitation

A live read-only smoke check used `qwen2.5-coder:3b` against an explicitly identified small implementation fixture and real passing unittest evidence. The first response produced repetitive, incorrect coverage complaints; the tightened contract bounds findings and requires exact source citations. The second response met those grounding checks but still incorrectly rejected `name.strip()` as stripping something other than the name. Grounding validates references, not reasoning. These actual observations are not a model-quality benchmark, and no successful engineering run is claimed from them. Inspect review findings yourself; selecting/evaluating a stronger local model remains an important next refinement. The fixture evidence is retained under `.workspaces/7c6a25c7-955d-492f-adcd-7c4e20ccfaea/review-smoke-grounded.json`.
