# Phase 2: task contracts and workflow state

## What this phase implements

Validated, immutable Pydantic contracts for task inputs, lifecycle records,
engineering results, completed execution history, and workflow snapshots. There
are no agent implementations, graph execution, repository operations, database
calls, or new HTTP endpoints. Models are definitions, not fabricated results.

All domain models reject unknown fields. Tuple collections and frozen nested
models prevent accidental in-place edits. JSON round trips preserve validated
nested models, UUID identities, enums, and timezone-aware UTC timestamps.
`schema_version=1` identifies the workflow snapshot contract; it is not a
database migration system.

## Files and responsibilities

```text
src/autonomous_engineering/
    domain/
        __init__.py
        base.py         # validation primitives and model policy
        tasks.py        # request, identity, lifecycle, transition errors
        results.py      # analysis, plan, change, test, review, report contracts
        execution.py    # agent identities, errors, completed execution records
    workflows/
        __init__.py
        state.py        # shared snapshot, partial update, merge rules
tests/
    test_tasks.py
    test_results.py
    test_workflow_state.py
```

`domain` imports no FastAPI, LangGraph, database, or LLM provider code.
`workflows` depends on domain contracts. The API remains unchanged. An
application service and graph adapter will use these contracts in later phases.

## Task lifecycle

| Current status | Allowed next statuses |
| --- | --- |
| `pending` | `running`, `cancelled` |
| `running` | `succeeded`, `failed`, `cancelled` |
| `succeeded`, `failed`, `cancelled` | None |

Same-status transitions are rejected. Repair attempts happen while the task is
running; they do not restart a terminal task. Future resubmission should create
a new task. `TaskRecord.transition()` returns a new validated record, preserves
identity, and rejects naive/backwards transition timestamps. Timestamp
invariants are also validated when deserializing saved records.

The task request contains the source repository reference and user's request.
`WorkflowState.workspace_path` is separate and remains absent until a future
workspace provisioner assigns it. Accepting a repository reference does not
authorize or perform any host access.

## Structured results and evidence

- Analysis identifies languages, frameworks, dependencies, relevant files, and
  architecture. A plan contains interpretation, steps, risks, and test strategy.
- Code changes identify a relative file, change kind, and explanation. They are
  metadata about the current net diff, not executable patches; Phase 6 adds
  actual patch operations and artifacts.
- Tests distinguish `passed`, `failed`, `error`, and `skipped`. Non-skipped
  outcomes require execution records. Passes require successful command exits;
  failures require nonzero exits or measured failures; errors require execution
  errors/timeouts. Skipped execution has no command records or measured counts.
- Test counts are optional and have no inferred defaults. An exit code of zero
  does not tell us how many tests ran. When counts exist, a passing result must
  have at least one pass and no failures. Counting/parser and command-selection
  policy belong to the future test execution system. These models validate
  consistency; they cannot prove that supplied evidence was actually measured.
- Reviews cannot approve unresolved high/critical findings. Rejected reviews
  require actionable findings. Line references require file references.
- A report summary has a terminal outcome and limitations. The original request,
  analysis, plan, changes, tests, and review remain in the enclosing state. The
  future Report Agent can compose a full report from these without copying all
  structured results into another nested model.

Relative file references reject absolute paths, drive/UNC paths, NULs, and `..`
traversal. They normalize relative Windows separators. This is syntactic
validation only: symlinks, filesystem permissions, workspace root confinement,
and execution isolation still require future tools and adapters.

## Execution history

Each completed record identifies the task, run, unique execution, agent, and
attempt. It includes bounded input/output summaries, success/failure,
timezone-aware timestamps, measured duration, and a structured error on failure.
Successful executions require an output summary and no error. Durations must be
finite and nonnegative; the future runner supplies them from a monotonic clock.
No duration or token/cost metrics are invented here.

History contains completed executions only; `current_agent` identifies the
currently active node, if any. Live start events/streaming and durable storage
arrive with observability. Error summaries and execution records are caller
supplied; the runner must redact secrets before constructing them.

## State updates

`WorkflowState.apply(WorkflowUpdate(...))` applies one sequential update atomically
and returns a new validated snapshot. It does not change the original if
validation fails. It is not a concurrent reducer or a persistence transaction.

| Field/update | Semantics |
| --- | --- |
| Task/run identity, request, workspace, budget | Not writable through node updates |
| `status` | Uses the task lifecycle transition method; cannot be cleared |
| `current_agent` | Replaces active agent; explicit `None` clears it |
| Analysis, plan, tests, review, report | Replaces latest result; explicit `None` clears it |
| `changes` | Replaces the complete current net-diff metadata, with unique file paths |
| `executions`, `errors` | Appends in supplied order |
| `development_attempt_increment` | Adds zero or one; rejects budget overflow |

Omitting a replacement field preserves it. Serialize partial updates using
`model_dump_json(exclude_unset=True)` or `model_dump(exclude_unset=True)` to
preserve omission semantics. Serializing a full snapshot does not require this.

Invalidation happens before explicit replacements in the same update:

| Updated field/action | Cleared downstream fields |
| --- | --- |
| Analysis | Plan, changes, tests, review, report |
| Plan | Changes, tests, review, report |
| Changes or new development attempt | Tests, review, report |
| Tests | Review, report |
| Review | Report |

This prevents old verification from surviving a new development attempt. If a
producer deliberately supplies several new results in one atomic update, those
explicit results are validated and retained. Provenance checking against actual
Git revisions belongs to later execution tooling. Historical execution records
remain available after current results are invalidated.

Executions with foreign task/run identities or duplicate execution IDs are
rejected. Appending the same event twice is an error, not automatic deduplication;
future checkpoint/replay adapters must account for that.

An active agent requires a running task. Terminal tasks must clear it. A
successful workflow requires passing tests, approved review, and a success report.
Failure/cancellation may have incomplete results and may precede report creation;
if a terminal snapshot has a report, its outcome must match. Finish reporting
before sealing the workflow because `apply()` rejects all terminal updates.
The domain TaskRecord alone handles lifecycle; workflow completion evidence is
an orchestration rule enforced by WorkflowState.

## Example without agent execution

```python
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate

state = WorkflowState(task=TaskRecord(request=TaskRequest(
    repository_path="C:/repositories/example",
    user_request="Fix the empty-input bug",
)))
state = state.apply(WorkflowUpdate(status="running", current_agent="supervisor"))
serialized = state.model_dump_json()
restored = WorkflowState.model_validate_json(serialized)
assert restored == state
```

This example constructs state only. It does not inspect the repository or invoke
an agent. The attempt budget is data validation; automated routing/retries arrive
in Phase 9, not here.

## Run and test

Use the existing environment from the project root; no new dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest -W error
.\.venv\Scripts\python.exe -m uvicorn autonomous_engineering.main:create_app --factory --reload
```

For a fresh environment, follow the installation steps in the README.
The tests cover the lifecycle matrix, invalid snapshots, UTC/JSON round trips,
path references, contradictory test evidence, review decisions, record identity,
history append, result replacement/invalidation, budget limits, and completion.
Test fixtures are synthetic validation data, not real autonomous-task outcomes.

## Phase 3

Install LangGraph and introduce a small graph adapter around these contracts.
Choose explicit state channels and update handling; ensure graph execution and
checkpoint serialization preserve these validation and merge rules. Add routing
and graph integration tests without pretending the future engineering agents
exist. Decide how a first honest workflow terminates before the Analyzer arrives
in Phase 4. No LLM providers or database are required yet.

References: [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/),
[model_copy validation caveat](https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_copy),
[LangGraph state and reducer contracts](https://reference.langchain.com/python/langgraph/graph/state).
