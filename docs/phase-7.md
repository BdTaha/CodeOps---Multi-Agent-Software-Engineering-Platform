> Historical milestone: current v1 architecture and behavior are documented in
> [architecture](architecture.md), [README](../README.md) and [demo](v1-demo.md).

# Phase 7: real test execution

The approved development continuation now runs `develop_implementation`,
`run_tests`, and `finalize_development`. Tests execute only when the user chooses
**Run unittest tests after development** in the React frontend before approval.
The monitor API accepts `run_tests: true` with the single-use approval ID;
omitting it skips execution. The legacy monitor remains development-only.

## Structure

```text
src/autonomous_engineering/
  agents/tester.py                    # Selection, process interface, outcome interpretation
  infrastructure/test_process.py     # Fixed command, bounded output and time, process cleanup
  workflows/development.py           # Development → tests → honest final report
  monitor.py                         # Explicit execution choice and existing run lock
  core/config.py                     # Validated test timeout
frontend/src/Workspace.tsx            # Trust choice and actual output
frontend/src/Results.tsx              # Outcomes without invented counts
tests/test_test_execution.py          # Real subprocess and workflow checks
examples/developer-demo/tests/        # Existing unittest behavior checks
```

## Supported execution

This first adapter discovers standard-library unittest cases in `tests/test*.py`
using the current backend interpreter. Nested discovery follows unittest's
package rules. Repository dependencies must already exist in that interpreter;
dependencies are never installed automatically. Pytest functions, JavaScript,
and other frameworks require later adapters. Zero collected tests returns a
nonzero exit status. Missing test files produce `skipped` with no process evidence.
Planner suggestions remain prose and are never executed as shell commands.

The child uses Python `-I -B`, a fixed trusted bootstrap, the validated managed
snapshot as its working directory, no interactive stdin, and a minimal environment
without inherited provider credentials or PYTHONPATH. Its default wall-clock
timeout is 60 seconds (`ASE_TEST_TIMEOUT_SECONDS`, maximum 300). Output is drained
in a separate thread and capped at 64 KiB; excessive output stops execution.
The recorded output is an excerpt of at most 3,000 characters. Ordinary descendants
are terminated using a process group on POSIX or taskkill's process tree on Windows.

**This is trusted local execution, not an OS security sandbox.** Test code can
read/write host files, access the network, or create processes. Path confinement
protects the file tools, not Python code. Escaped/detached descendants and malicious
code require container isolation, which remains Phase 11. Never use this adapter
for untrusted repositories. Tests may change their snapshot; no automatic retry,
test creation, original-source application, or runtime dependency installation occurs.
Snapshots remain filtered text copies, so missing binary fixtures or dependencies
can cause real failures; the report does not pretend those tests passed.

## Evidence and final status

The agent records the actual fixed command, exit code, monotonic duration, output
excerpt, timeout and execution error. It distinguishes passed, failed, error,
and skipped outcomes. Individual test counts remain unknown instead of parsing
possibly misleading console text. The UI shows the outcome when counts are absent.
Process success is test evidence, not proof the user's feature is correct or that
coverage is adequate. The demo's two tests cover existing plain/empty greeting
behavior; they do not establish whitespace handling by themselves.

Passing tests stop with `REVIEW_AGENT_NOT_IMPLEMENTED`; failed tests stop with
`TESTS_FAILED`, bounded execution failures with `TEST_EXECUTION_ERROR`, and skipped
tests with `TEST_VALIDATION_REQUIRED`. Overall tasks still fail honestly until
review is implemented. No approval of code quality is implied.

## Run

```powershell
.\scripts\frontend.ps1 build
.\.venv\Scripts\python.exe -m uvicorn autonomous_engineering.monitor:create_monitor_app --factory --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/ui/>. In Live mode, plan a focused task against
`examples/developer-demo`, review the files/plan, select the test execution option,
and approve. Inspect Test Agent details or Results for the real output.
Restart the monitor after changing backend code; restart loses pending approvals.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_test_execution.py -W error
.\.venv\Scripts\python.exe -m pytest -W error
```

Tests execute identified fixture suites and verify passes, assertion failures,
zero collection, absent files, timeout cleanup, output overflow, environment
filtering, workspace identity, denied execution without consent, source isolation,
measured agent records, and the required review boundary. No Ollama output is
substituted for real process evidence.
