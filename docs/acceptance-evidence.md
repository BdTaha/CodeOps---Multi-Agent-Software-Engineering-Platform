# Acceptance criteria and execution evidence

## Architecture

This layer synthesizes the existing **final successful** execution artifacts. It
does not run tests, perform another review, change the execution bridge, dispatch
assigned tasks or deliver code. Product requirements and coding plans remain
distinct. The existing Worker handles a separate, durable post-success evidence
queue before claiming its next execution job.

New linked runs freeze their criterion IDs, descriptions and ordering in the same
transaction as execution creation. Successful execution checkpoints atomically
queue evidence processing and move the EngineeringTask to Review. Runtime slots
are already released at the canonical terminal checkpoint. Review can therefore
show **Processing** briefly; acceptance waits until the evidence package is ready
or explicitly unavailable. Reading APIs never triggers mapping.

## Status semantics

| Display | Meaning |
| --- | --- |
| Verified by passing test evidence | A retained individual passing unittest result exists, references a real test method with assertions, and has an explicit deterministic criterion association. |
| Supported by implementation evidence | A recorded file change, requirement-specific reviewer observation, or validated semantic association suggests the requirement was addressed. This does not establish runtime behavior. |
| Not automatically verified | No usable association was materialized. Human verification is required; this is not a development failure. |
| Conflict — human review required | Final negative reviewer evidence overrides optimistic evidence. The underlying status remains unverified, with `conflict=true`, and both positive and negative sources remain visible. |

No quality percentages or guarantees are calculated. Supported criteria explicitly
say that no directly mapped passing check verifies the requirement. Acceptance
remains a human decision.

## Actual test evidence and conservative mapping

The current `TestExecution` contract stores command, exit code, duration, bounded
output excerpt, timeout and error. `TestResults` has a suite outcome and optional
counts, but **no structured per-test result collection**. The existing unittest
runner uses verbosity 2; its retained output may contain individual identifiers
and outcomes. Pytest currently uses `-q`, and npm output varies. An aggregate
`18 passed`, a zero exit code, or generic AI approval never verifies a criterion.

Version 1 derives unittest sources only from exact individual result lines in a
successful, error-free recorded unittest execution. Identifiers must resolve to
real methods in final `tests/*.py` source, including nested test directories. The
method must contain an assertion. Duplicate, absent, skipped, failed, ambiguous
or truncated-away results are not treated as passing evidence. A descriptive
unittest result split across its method/header and first docstring line is
recognized only when it matches that actual docstring.

Verified associations require the criterion to explicitly reference the test
identifier, or to match its docstring exactly after case/whitespace normalization.
For example, `The test_expired_reset_token check passes` can map to the recorded
passing test. Mentioning a test expected to fail does not produce verification.
This is evidence that a named check passed, **not a proof that its assertions
fully capture the business requirement**. Tests and their emitted results remain
project-provided evidence and require human scrutiny.

Changed-file summaries and requirement-specific final reviewer summaries can map
deterministically to Supported. Their references must exist in the final workspace
or the canonical deleted-file manifest. Generic short review approval supplies no
requirement-specific source.

Ambiguous natural-language associations may use the existing configured local
Ollama transport. Its schema permits only `(criterion_id, source_id)` associations
from bounded catalogs; it cannot output statuses, fabricated test identities,
file references or evidence prose. **Every semantic association is Supported at
most**, even when its selected source is a passing test. The server rejects an
unknown criterion/source or extra fields and makes the package unavailable rather
than accepting an invented reference. No provider selector or new provider is
introduced. Without a configured model, deterministic mapping is sufficient to
produce an honest package; unmatched criteria stay unverified.

Final negative findings without an exact deterministic requirement scope are
conservatively surfaced for all criteria with unresolved applicability. A model
cannot hide a finding by assigning it to an unrelated criterion. This may require
more human review than necessary, but avoids an optimistic Verified label.

Intermediate repair attempts remain in the existing trace. Only the final result
is used here. Each request-changes run creates a fresh independent package.

## Criterion identity and additive schema

Draft `AcceptanceCriterion` still contains only a description; product planning
models do not invent persisted IDs. Saved EngineeringTasks now expose
`PersistedAcceptanceCriterion` with a stable UUID and description.

`engineering_acceptance_criteria` retains its existing task/position primary key,
description and ordering, and adds a unique `id`. Under the existing startup
migration fence, old rows receive deterministic UUIDs derived from task ID and
position once; new criteria receive UUID4 identities. Reads never derive identity
from mutable text. Future editing must preserve existing criterion IDs and assign
new IDs to newly introduced criteria.

Four normalized tables are added:

- `acceptance_evidence_runs`: execution foreign key, immutable package version,
  mapper version (`acceptance-evidence-v1`), processing state, lease/owner,
  timestamps and processing error.
- `acceptance_run_criteria`: execution/criterion foreign keys, frozen description
  and position, verification status and conflict flag.
- `acceptance_evidence_items`: one criterion/source association, type, canonical
  artifact reference, bounded summary, negative/executed flags and mapping method.
- `acceptance_result_audits`: accepted execution, timestamp, local manual action,
  package/mapper version, evidence state/digest and unresolved acknowledgment.

Run and EngineeringTask identity come from the existing execution-link table;
evidence does not duplicate execution phase or entire logs. Source references
point to final changes, test execution/output lines or reviewer findings/summary.
Normal UI summaries stay bounded; full retained logs remain in Engineering.

Existing task/run history and prior acceptance records are preserved. Old runs
without a package report **Not generated**; migration never reconstructs historical
evidence. Previously accepted runs have no invented acknowledgment audit.

## Processing, restart and failure

New package states are `waiting` → `pending` → `processing` → `ready` or
`unavailable`. Failed/cancelled development packages become `not_generated`.
Mapping claims are transactional compare-and-set operations. Materialization
takes the existing workspace/project fence and checks processing owner/lease
before atomically saving all results and marking Ready. A competing worker cannot
save another package for that same run.

Pending work survives API/worker restart. An expired processing lease becomes
Unavailable with `EVIDENCE_INTERRUPTED`; it is not silently recomputed using
different artifacts or mapping logic. Provider, source validation or persistence
failure records `EVIDENCE_MAPPING_FAILED` and a canonical event. Development stays
successful, the task stays Review, and runtime concurrency is unaffected. No
partial Ready package or fabricated fallback is shown. This phase provides no
public rematerialization endpoint.

## Human acceptance and API

The existing `GET /engineering-tasks/{id}/execution` now includes
`acceptance_evidence`: state, version, mapper version, frozen criteria, statuses,
source records, counts when Ready, error and acceptance audit. Historical packages
are read through **`GET /tasks/{execution_task_id}/acceptance-evidence`**, including
originating EngineeringTask and run identity. No duplicate current-evidence route
is needed. Existing raw file, trace, test, review and delivery APIs remain.

`POST /engineering-tasks/{id}/accept` now accepts:

```json
{
  "revision": 7,
  "execution_task_id": "existing-execution-uuid",
  "evidence_version": "package-version-uuid-or-null-for-old-runs",
  "unresolved_acknowledged": true
}
```

Revision and accepted execution must still be current. Evidence version must match
the stored package. Acceptance during Processing is refused until it finishes.
Unverified criteria, conflicts, Unavailable or Not generated evidence require
explicit acknowledgment. All Verified criteria allow normal acceptance without
it. Supported criteria do not require this additional checkbox, but clearly state
the lack of directly mapped execution proof. This follows the requested separate
Supported/Unverified semantics.

Acknowledgment, evidence digest/version and `local_human_acceptance` action are
persisted atomically with the existing link acceptance and Done transition. There
is no named employee claim or new authentication system. Acceptance still does
not publish, merge, deploy or apply source edits.

## Review UI and how to run

The task's **Acceptance** tab is the default result-review tab. It shows counts,
criterion cards, real test identifiers/files/outcomes, source summaries, semantic
association labels and visible conflicts. **View test/diff/AI review** opens the
existing raw-artifact tabs. Execution history exposes each older package and its
acknowledgment audit. Feedback reuses the existing Request changes workflow.
Runtime wording now correctly says terminal execution releases the slot before
human result review.

Start the normal services in separate PowerShell terminals:

```powershell
.\scripts\frontend.ps1 build
.\scripts\run-platform.ps1 api
.\scripts\run-platform.ps1 worker
```

Keep the currently configured Ollama model available and Docker running for
container tests. Assign an active AI developer to a task with finished dependencies,
choose Run with CodeOps, review/approve its coding plan, then inspect Acceptance
after successful execution. To exercise deterministic verification, use an
explicit existing test identifier in a criterion, or an exact requirement
docstring in the relevant test. Unmatched requirements remain honest unresolved
items. Review them manually and acknowledge before accepting, or request changes.

Back up `engineering.db` before upgrading and restart API and worker together.
Automatic migration is idempotent on SQLite and PostgreSQL.

## Tests and changed files

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_acceptance_evidence.py
.\.venv\Scripts\python.exe -m pytest
# Optional disposable PostgreSQL database:
$env:ASE_INTEGRATION_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:PORT/DATABASE'
.\.venv\Scripts\python.exe -m pytest tests/test_acceptance_evidence.py tests/test_task_execution_bridge.py tests/test_team_migration.py
```

The tests use the real existing worker, snapshot editing, unittest process and
review flow with explicit test providers. Coverage includes concrete test mapping,
weak sources, conflicts, invented source rejection, provider transport, failure
isolation, processing/restart states, frozen historical requirements, stable legacy
IDs, acknowledgment/audit, delivery separation and SQLite/PostgreSQL persistence.
The full suite retains existing Planning, Teams, capacity, direct execution and
Docker/Git delivery coverage.

Added backend files: `domain/acceptance_evidence.py`,
`application/acceptance_mapper.py`, `infrastructure/acceptance_tables.py`,
`infrastructure/acceptance_store.py`, `infrastructure/ollama_evidence.py`.
Modified backend files: `domain/product_planning.py`,
`infrastructure/planning_store.py`, `infrastructure/team_migrations.py`,
`infrastructure/task_execution_tables.py`, `infrastructure/task_execution_store.py`,
`application/worker.py`, `api/task_executions.py`.
Frontend: added `AcceptanceEvidence.tsx`; modified `TaskExecutionPanel.tsx`,
`productTypes.ts`, `product.css`. Tests: added `test_acceptance_evidence.py`, updated
`test_task_execution_bridge.py`. Docs: this guide, `task-execution-bridge.md`, README.

## Limits and recommended next phase

Version 1 uses retained unittest output rather than a structured runner report.
Pytest/npm aggregate summaries cannot grant Verified status. Indirect/helper-based
assertions, dynamic tests and absent/truncated individual results may remain
unverified. Semantic mapping quality depends on the configured model; invalid
output makes evidence unavailable. Test naming/docstrings and actual assertions
require human judgment. Conservative unresolved reviewer scope may flag unrelated
criteria. Old historical packages are not generated automatically, and there is no
public evidence retry/version migration interface.

The recommended next phase is **runner-produced structured per-test reports and
explicit requirement/test declarations**, with final source/test fingerprints and
better targeted conflict scope. It is not implemented here. Hosted previews,
browser-driven validation, automatic dispatch/acceptance/delivery and provider
switching remain outside this phase.
