# CodeOps v1 demo

## Prerequisites and startup

Python 3.11+, Node 22.12+, pnpm 11.25.0, Git and Docker Desktop Linux engine.
Install/build using README Quick start. Configure a capable structured-output model
in Settings · Models, or pull Ollama and set ASE_OLLAMA_MODEL. Catalog availability
is not a guarantee the model can complete this task. Optional GitHub delivery
requires importing a repository and configuring a token; commit export needs no
GitHub credentials.

Build images from the CodeOps root:

```powershell
docker build -t ase-runner:local -f containers/runner.Dockerfile .
docker build -t codeops-preview-python:local -f containers/preview-python.Dockerfile .
```

Run in three terminals:

```powershell
.\scripts\run-platform.ps1 api
.\scripts\run-platform.ps1 worker
.\scripts\run-platform.ps1 preview
```

Open http://127.0.0.1:8765/ui/. Back up the existing database and retained workspaces
before an upgrade; restart all three services together to load the additive schema.
Do not delete your database or preview volumes as a migration procedure.

## Prepare a fresh demo source

The existing examples/developer-demo now includes a dependency-free API,
registration form, validation.normalize_email helper, greeting module and tests.
Registration intentionally returns 501 until implemented. This is an engineering
exercise, not production authentication; no passwords or external services.

Choose a NEW directory inside ASE_REPOSITORY_ROOT and outside ASE_WORKSPACE_ROOT.
For the default repository root (this checkout), use:

```powershell
New-Item -ItemType Directory -Path imported -Force | Out-Null
Copy-Item -LiteralPath examples/developer-demo -Destination imported/v1-developer-demo -Recurse
Push-Location imported/v1-developer-demo
& ../../.venv/Scripts/python.exe -m unittest discover -s tests -v
Pop-Location
```

Run the baseline tests from the copied source directory instead if imports fail:
`python -m unittest discover -s tests -v`. Do not copy over an existing demo; choose
a fresh name for another attempt. Optionally initialize Git in the copy and commit
the baseline for additional source-diff inspection. CodeOps commit export can
create its own baseline/change history without a source Git repository.

In **Projects**, register the absolute copied path with name developer-demo.
Save a baseline checksum list or a clean source Git status. Do not use the CodeOps
application's own source as this demo target.

## Exact product and engineering journey

1. Open **Planning**, select developer-demo and enter:
   **Add user registration with input validation and persistent storage.**
   Keep it scoped: reuse validation.normalize_email; name/email in SQLite;
   reject malformed and duplicate email; unittest tests; preserve app.py API.
2. Click **Plan with CodeOps**. Expect Queued → analyzing → Draft. Inspect
   **Planning basis · Repository-grounded**, sampled files and limitations.
   If Goal-only appears, resolve the stated source problem before this demo.
3. Inspect epics, tasks, dependencies and criteria. Change an estimate (e.g. 8h
   to 5h) and add **Existing validation helper is reused** to the implementation
   task. Add/remove/reorganize proposed work if necessary. Model task count/refs
   vary; use the actual draft, not a promised T2 or fixed CO number.
4. **Save changes**. Expect a higher revision. Refresh and verify edits persist.
   Before approval, Board has no tasks from this draft and Teams has no draft load.
5. **Approve Plan & Create Work Items**. Expect Approved and T→CO mapping.
   Board shows these tasks alongside older approved work. This is the first point
   at which permanent task numbers are allocated.
6. In **Teams → Workspace members**, create/reuse Backend Agent: AI, developer
   execution role, active, available, Backend skill, concurrency 1.
7. In **Project teams**, create Backend Squad and add that member through project
   membership. Assign a Backend task from Board details or Engineering. Confirm
   queue depth changes but no execution starts automatically.
8. Choose a task with no blockers. Complete prerequisite work normally; don't mark
   unimplemented dependencies Done merely to bypass the guard. A single coherent
   registration task is acceptable for this small demo.
9. Open its **Engineering → Overview**. Header owns the main **Run with CodeOps**
   action. Sidebar is compact; Overview explains any assignment/dependency blocker.
10. Click **Run with CodeOps**. Expect isolated snapshot/analysis, then coding plan.
    Inspect **Plan**, scope, intended files/tests and assumptions.
11. Approve the coding plan explicitly. Choose **unittest**, **Docker** and a bounded
    attempt limit (e.g. 3). Development → Tests → Review should produce real diff,
    recorded commands/output and reviewer findings. A repair may occur within scope.
12. On success, task is **Review**, not Done. Inspect **Diff**, **Tests**, **Review**
    and **Acceptance**. Supported/Unverified/conflict evidence is not a verified
    result; resolve or acknowledge unresolved items deliberately.
13. In project Preview settings, enable Web / Python, start argv
    `["python","app.py"]`, port 8000, health `/health`, open `/`, no external services,
    no build commands. Keep build networking disabled; this demo needs no packages.
14. Open **Preview → Start preview**. Expect Queued → Building → Starting → Ready,
    then an actual loopback URL. Submit Ada / ada@example.com: HTTP 201. Try duplicate
    and invalid data: reject with HTTP 400. SQLite stays in the disposable volume.
    Restarting a preview creates fresh runtime data, not durable production storage.
15. Stop preview. Click **Request Changes** once:
    **Use the project's existing validation helper instead of duplicating validation.**
    If already reused, ask a concrete improvement instead (e.g. an invalid-name test).
16. Expect a new execution link and preserved prior run in **History**. Request Changes
    starts from registered source plus retained feedback/context, not an automatically
    applied old workspace. Inspect/approve its new coding plan.
17. Let execution/tests/review/evidence finish. Inspect the current and previous diffs;
    previous runs are read-only. Repeat the preview checks if desired, then stop it.
18. Click **Accept result**, reviewing unresolved evidence acknowledgment if offered.
    Expect task **Done**, accepted review state and no automatic delivery.
19. Explicitly choose **Create draft PR** for an imported/configured GitHub source,
    otherwise **Create commit** (commit export). Inspect the commit/ZIP containing
    baseline and reviewed changes. Local apply is a separate guarded action.
20. Verify the original source checksum/Git diff still matches baseline before delivery
    and after commit export. Nothing was auto-merged or deployed.

## Failures and recovery

* Invalid model draft: visible generation error; improve goal/model and submit a new
  draft. Don't replace it with fabricated feature content.
* Save/approval 409: another tab changed revision; reload, reconcile edits, approve
  the exact saved revision. Invalid criteria/dependency graph returns 422.
* Run blocked: check active membership, developer role, offline state, AI slots and
  incomplete dependencies. Assignment is separate from dependency readiness.
* INVALID_EDIT / DEVELOPMENT_SCOPE: inspect Plan and actual error. A run from fresh
  source may require created files even when a previous run added them. Retry is
  explicit; models cannot write paths outside approved scope.
* Tests fail: inspect recorded output and environment; project packages must be in
  the runner image. Docker failures never silently switch to local host execution.
* Preview fails: check Docker Linux engine, image, argv, container port/health path;
  inspect logs. Preview failure does not erase successful development or accept it.
* Acceptance conflict: artifact/run/evidence changed; reload current evidence.
* GitHub delivery unavailable: use explicit commit export, not an invented PR URL.

## Cleanup and reproducible validation

Stop active previews; TTL/reconciliation removes CodeOps-owned containers/volumes.
Keep SQL, run snapshots and exports for demonstration evidence. Stop services only
when no work is running. Remove only your dedicated disposable source/test folder
if no longer needed; never reset the normal developer database.

The automated backend journey uses actual API, SQL, repository inspection,
workspace edits, subprocess unittest, human decisions and Git export. Models are
explicit deterministic fixtures, so it tests orchestration rather than LLM quality:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v1_journey.py -q
$env:ASE_INTEGRATION_PREVIEWS='1'
.\.venv\Scripts\python.exe -m pytest tests/test_v1_journey.py -q
```

The second command additionally launches a real Docker preview and submits a real
registration request. Normal CI does not require Docker or external inference.
See [verification](verification.md) for what was actually observed locally and
[screenshot checklist](screenshots/README.md) for portfolio captures.
