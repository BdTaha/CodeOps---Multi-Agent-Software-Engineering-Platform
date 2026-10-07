# Architecture and phased implementation

> The platform now includes SQL task/trace storage, fenced independent workers, bounded
> repair routing, Docker execution, delivery adapters and real evaluation. See
> [the current runbook](platform.md). Sections below retain the original phased design.

## Requirements and scope

The system must perform engineering work on a repository, including actual code
changes, test execution, review, and bounded repair loops. It needs structured
results and traceable decisions, not just a conversation transcript. It must be
small enough for one developer to maintain and explain.

Start with a modular Python backend in one package. FastAPI handles HTTP;
Pydantic validates boundaries; LangGraph will coordinate execution. PostgreSQL
will provide durable task and trace storage. Separate worker execution from
HTTP request lifetimes when tasks become executable. No microservices or queue
are justified in this skeleton. Redis is deferred until a concrete requirement
such as worker coordination justifies it.

## Module boundaries

| Module | Responsibility | Excluded responsibility |
| --- | --- | --- |
| `api` | HTTP validation, dependency injection, status codes, responses | Graph routing, prompts, SQL, repository mutation |
| `core` | Validated settings and logging | Business state, generic utility dumping ground |
| `domain` (Phase 2) | Task lifecycle and structured analysis, plan, change, test, review, report contracts | FastAPI, SQL, provider clients |
| `application` (when use cases arrive) | Submit/query/execute task use cases; narrow interfaces where external boundaries need them | HTTP details, concrete database/provider implementations |
| `workflows` (Phase 3) | Typed graph state, nodes, conditional edges, retry budgets, coordination | Raw filesystem operations, SQL, HTTP transport |
| `agents` (Phases 4–9) | Specialized reasoning with validated inputs/outputs | Arbitrary shell or filesystem access, direct persistence |
| `tools` (as agents need them) | Workspace-scoped file inspection/change and test operations, with explicit capabilities | Global host access, graph routing |
| `infrastructure` (as integrations arrive) | Concrete PostgreSQL stores, LLM clients, workspace and process/container adapters | Owning task lifecycle policy |

`api`, `core`, `domain`, workflows, read tools, local workspace infrastructure,
the Repository Analyzer, the read-only local Ollama Planner, and an explicitly
approved snapshot Developer now exist.
See [Phase 2](phase-2.md) for contracts, [Phase 4](phase-4.md) for inspection
boundaries, [Phase 5](phase-5.md) for planning, and [Phase 6](phase-6.md) for
approval identities, scoped text edits, diff artifacts and the separate LangGraph
development continuation. Create the other
directories with their first real implementation, rather than empty interfaces
or fake agents. `main.py` will wire concrete dependencies at the outer boundary.
Domain contracts remain independent; graph and infrastructure code can depend
on them, not the reverse.

Target package shape (modules are introduced incrementally):

```text
autonomous_engineering/
    main.py
    api/
    core/
    domain/
    application/
    workflows/
    agents/
    tools/
    infrastructure/
```

## LangGraph and agents

LangGraph is the stateful orchestration engine, not the entire backend. Its
StateGraph nodes will call agent operations and return explicit state updates.
The supervisor will route based on task progress and validated outcomes; it
will have no code-writing tools. Tests and review can route back to development,
subject to attempt limits and terminal failure conditions. Reporting must also
cover unsuccessful tasks.

Graph state will reference typed domain results. In Phase 2, define identities,
task status, analysis/plan/change/test/review results, errors, and execution
history; then choose explicit merge rules before implementing the graph.
Keep routing decisions separate from the persisted task lifecycle. Prefer file
references, bounded excerpts, and patch artifacts over full repository contents
in shared state. Do not use an ever-growing chat transcript as workflow state.

Analyzer and planner receive read capabilities. Developer receives scoped change
capabilities. Test execution goes through an execution adapter. Reviewer receives
source, diffs, and actual test evidence. Report generation uses recorded results.
The approval policy for plans must be explicit before code mutation is enabled.
LangChain/provider adapters can support structured LLM outputs when needed; they
do not belong in domain models or route handlers.

## Persistence, API, and observability

Later task routes call application services. Long-running execution must not
depend on keeping an HTTP connection open. Do not treat an in-process background
task as a durable job queue. Select a worker dispatch design when execution and
task management are implemented.

PostgreSQL will hold task records, final results, and execution events. LangGraph
checkpoints support workflow resumption and have a different purpose from the
public task record and trace. Define their consistency/recovery contract when
persistence arrives; do not duplicate their responsibilities blindly.

Each node execution should produce an event with task/run/attempt identity,
agent name, bounded input/output summaries, outcome, UTC start/end timestamps,
duration measured with a monotonic clock, and structured errors. Record failed
executions as well as successful ones. Redact secrets and avoid persisting raw
repository contents or prompts by default. The future trace API reads these
events; it does not reconstruct them from unstructured console logs.

Phase 1 logs real service startup/shutdown only. It does not emit fabricated
agent events, token usage, evaluation metrics, or test outcomes.

## Repository and execution boundaries

Future tasks operate on isolated Git checkouts with a workspace identity.
File tools must resolve paths, reject traversal and escapes through symlinks,
and enforce the workspace root. Centralize process execution behind an adapter
that can later use Docker with time/resource limits, controlled network access,
and restricted mounts. Running repository tests is arbitrary code execution:
path checks alone are not an execution sandbox.

No repository operations or subprocess endpoint exists in Phase 1. Docker-based
repository execution stays in Phase 11. Containerizing the API and wiring a
PostgreSQL Compose service can be introduced when there is a real integration
to run; inert services are unnecessary today.

## Phase 1 decisions

- Use a `src/` layout so tests import the installed package as deployment will.
- Use an app factory to inject settings without global configuration caches.
- Use Pydantic Settings for environment validation and optional `.env` loading.
- Use standard-library logging; no external observability stack is needed yet.
- Expose `/health` as liveness only. Add readiness when dependencies exist.
- Let invalid configuration fail startup with its validation error. Do not add
  a blanket exception handler that hides programming errors; add specific error
  mappings as application error contracts arrive.
- Install only dependencies used today. LangGraph, LangChain, PostgreSQL clients,
  Docker/Compose services, and Redis arrive with their owning phases.
- No frontend, GitHub integration, task APIs, fake implementations, or benchmarks.

## Phase 2 acceptance criteria

1. Validated task input and documented task lifecycle transitions.
2. Structured engineering result contracts with real outcome semantics, including
   failure, skipped tests, rejected review, and incomplete execution.
3. Typed serializable workflow state with explicit append/replace update rules.
4. Identity and attempt/error metadata sufficient for later traces and retries.
5. Tests for validation, serialization, and illegal lifecycle transitions.

Phase 2 contracts and validation tests are implemented. The planning graph performs
supervisor preflight, isolated text snapshot preparation, and real repository
analysis and configured local draft planning, then stops for human approval.
Phase 6 adds a separate finite LangGraph continuation that develops the approved
snapshot and stops before test execution. Test, Review and repair-loop agents
and database integration are not implemented yet.

## Framework references

- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [FastAPI lifecycle testing](https://fastapi.tiangolo.com/advanced/testing-events/)
- [Starlette TestClient and its HTTPX2 dependency](https://starlette.dev/testclient/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [LangGraph API overview](https://reference.langchain.com/python/langgraph/overview)

## Phase 7 execution adapter

`agents/tester.py` selects existing Python unittest files and interprets measured evidence. `infrastructure/test_process.py` owns the fixed interpreter command, minimal child environment, output limit, timeout, and ordinary process-tree termination. The approved development graph records the test stage before final reporting. The monitor requires a separate explicit `run_tests` choice; no model command is executable. This trusted-local adapter is not an OS sandbox. Review and repair routing remain Phase 8 and 9. See [Phase 7](phase-7.md).

## Phase 8 review boundary

`agents/reviewer.py` assembles bounded full-file evidence and validates structured decisions/references. `infrastructure/ollama_reviewer.py` adapts the existing local-only JSON-schema transport. The development graph reviews only passing test evidence, records rejected/provider-failed reviews, and finalizes success only when both tests and review approve. Resulting-file hashes prevent reviewing a diff against altered changed files; snapshot fingerprints invalidate changes during model inference. `/monitor/activity` exposes actual node starts for UI progress. Repair loops and durable execution remain later work. See [Phase 8](phase-8.md).
