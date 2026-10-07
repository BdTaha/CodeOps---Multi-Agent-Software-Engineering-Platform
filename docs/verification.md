# Verified on 2026-10-06

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
