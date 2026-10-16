# CodeOps: the complete beginner's guide

This guide explains the current CodeOps interface, from opening the app to reviewing and delivering an AI-generated change. You do not need to understand its internal architecture to follow it.

**Read this first:** CodeOps asks you to approve work at several points. Creating a plan, assigning an AI member, and accepting a result are different actions. None of them automatically deploys your application.

## Contents

1. [What CodeOps is for](#1-what-codeops-is-for)
2. [Words you will see](#2-words-you-will-see)
3. [Start and stop CodeOps](#3-start-and-stop-codeops)
4. [Find your way around](#4-find-your-way-around)
5. [Models: connect the AI](#5-models-connect-the-ai)
6. [Projects: add your code](#6-projects-add-your-code)
7. [Planning: turn an idea into approved tasks](#7-planning-turn-an-idea-into-approved-tasks)
8. [Board: see and open the work](#8-board-see-and-open-the-work)
9. [Teams: create members and assign ownership](#9-teams-create-members-and-assign-ownership)
10. [Engineering: run and inspect a task](#10-engineering-run-and-inspect-a-task)
11. [Every Engineering tab](#11-every-engineering-tab)
12. [Preview settings: configure how your app runs](#12-preview-settings-configure-how-your-app-runs)
13. [Accept, request changes, and deliver](#13-accept-request-changes-and-deliver)
14. [A first task from start to finish](#14-a-first-task-from-start-to-finish)
15. [Troubleshooting and disabled buttons](#15-troubleshooting-and-disabled-buttons)
16. [Daily checklist and current limits](#16-daily-checklist-and-current-limits)

## 1. What CodeOps is for

CodeOps helps you organize software work and ask AI agents to implement it. It keeps the proposal, generated files, test results, AI review, and your final decision together so you can inspect what happened.

You provide an existing project and a goal. CodeOps proposes smaller tasks. You edit and approve those tasks, assign ownership, and explicitly start the tasks you want an AI developer to work on.

The usual journey is:

```text
Add project → Configure model → Describe goal → Review product draft
→ Approve product plan → Assign a task → Run with CodeOps
→ Review coding plan → Approve coding plan → Development, tests, AI review
→ Inspect result and optionally preview → Accept or request changes
→ Explicitly export, apply locally, or create a draft pull request
```

**Your role:** decide what to build, check the proposed scope, inspect the result, and choose whether to accept and deliver it.

**The AI's role:** propose work, analyze a sampled copy of the repository, generate changes, and review the retained result. AI can make mistakes, including mistakes in review comments.

The source project is copied into an isolated working area for execution. Generated edits there do not automatically modify your original project. **Apply locally** is the delivery action that writes reviewed files back to the original repository.

## 2. Words you will see

| Word | Plain-language meaning |
| --- | --- |
| Workspace | Your local CodeOps environment. The sidebar's **Workspace** button opens the Engineering area; **Workspace members** in Teams means the shared member list. |
| Project / repository | The folder containing the application's source code. A repository often has Git history, but local registration itself uses a folder path. |
| Goal | The outcome you want, such as “Add registration with email validation.” |
| Product plan | A proposed breakdown of a goal into epics and engineering tasks. It lives in Planning. |
| Draft | A proposal you can edit. It is not yet actionable work. |
| Epic | A group of related tasks, such as “User registration.” |
| Task | One work item with a description, owner, estimate, dependencies, and acceptance criteria. |
| `E1`, `T1` | Temporary references to an epic or task inside a draft. |
| `CO-1` | A permanent key allocated to approved work. Your actual number may differ. |
| Squad | A project-specific group of members, usually covering particular technical areas. |
| Assignee / owner | The member responsible for a task. Assignment does not start execution. |
| Dependency | Another task that must be Done before this task can run. |
| Acceptance criteria | Observable requirements the finished result should satisfy. They are not automatically completed checkboxes. |
| Coding / implementation plan | The file-level plan for one execution. It appears in Engineering → Plan and needs a separate approval. |
| Run / execution / attempt | A recorded effort to implement a task. A task can have several runs. Individual operations can also have numbered attempts within a run. |
| Snapshot | The isolated copy of source used for a run. |
| Diff | A comparison showing added and removed lines. |
| Model / provider | The AI model and the service supplying it. Ollama supplies models locally; hosted providers supply them remotely. |
| Review | Either an AI code review or a stage waiting for your human decision. Check which screen you are viewing. |
| Preview | A temporary local environment running the generated application so you can inspect its behavior. |
| Delivery | Exporting reviewed code, writing it back locally, or publishing a draft GitHub pull request. |
| Pull request / PR | A proposed change on GitHub that another person can review and merge later. |

## 3. Start and stop CodeOps

### 3.1 If CodeOps is already installed on this computer

1. Open the CodeOps project folder in PowerShell. For this installation:

   ```powershell
   Set-Location 'C:\Users\tahab\Desktop\My Project'
   ```

2. Start Ollama if the active connection uses it. Docker Desktop's **Linux engine** must be running if you will use Docker tests or application previews.
3. Open **three separate PowerShell terminals**, each in the CodeOps folder.
4. In the first terminal, run:

   ```powershell
   .\scripts\run-platform.ps1 api
   ```

5. In the second terminal, run:

   ```powershell
   .\scripts\run-platform.ps1 worker
   ```

6. In the third terminal, run:

   ```powershell
   .\scripts\run-platform.ps1 preview
   ```

7. Leave these terminals open. Visit **http://127.0.0.1:8765/ui/** in your browser.

| Service | Why it is needed |
| --- | --- |
| `api` | Serves the interface and receives your actions. |
| `worker` | Processes queued planning and coding work. Without it, the interface can load while work stays queued. |
| `preview` | Starts and cleans up temporary application previews. It is needed for previews, not ordinary navigation. |
| Ollama | Supplies the model when your selected route uses local Ollama. |
| Docker | Runs container tests and previews when selected. |

You normally run these commands each time you want to use the system. Do not start a second API if one is already using port 8765.

### 3.2 First installation or a newly cloned checkout

The detailed prerequisites and installation commands are in the [README Quick start](../README.md#quick-start-windows). Install Python 3.11+, Node 22.12+, pnpm 11.25.0, and Git. Install Docker Desktop with its Linux engine for container execution.

The initial setup creates the Python environment, installs dependencies, copies `.env.example` to `.env`, builds the frontend, and builds the required Docker images. **Preserve an existing `.env`; it contains your local configuration.** Configure the model in Models before asking CodeOps to generate work.

The initial Docker images include:

```powershell
docker build -t ase-runner:local -f containers/runner.Dockerfile .
docker build -t codeops-preview-python:local -f containers/preview-python.Dockerfile .
```

Node previews need their corresponding image and project configuration; see [local previews](local-previews.md).

### 3.3 After updating CodeOps

Back up the database and retained workspaces before upgrading. Follow any setup changes in the README. Rebuild the interface with:

```powershell
.\scripts\frontend.ps1 build
```

Restart API, worker, and preview worker together when backend code or database structure changes. Refresh the browser to load the new interface. Changing Models routing through the UI does not require restarting workers.

### 3.4 Stop CodeOps

1. Stop running previews with **Stop Preview**.
2. Let active coding work finish, or use **Cancel execution** and wait for the recorded cancellation.
3. Press **Ctrl+C** in each service terminal.

Closing the browser is not a cancellation. Do not delete the database or working folders to stop or reset a task.

## 4. Find your way around

The far-left sidebar is the main navigation. It starts as an icon rail unless you previously chose to expand it. Hover over icons to see their names.

| Control | What it does |
| --- | --- |
| Arrow at the very top | **Right arrow:** expand the global sidebar. **Left arrow:** collapse it. Your choice persists across all sections and browser reloads. |
| CodeOps logo | Opens Projects. |
| **New plan** | Opens Planning. It does not itself submit a goal or create a new draft. It is visible in the expanded sidebar. |
| **Projects** | Lists registered source projects. |
| **Planning** | Creates, edits, saves, and approves product plans. |
| **Board** | Shows approved tasks grouped by status. |
| **Teams** | Manages members, project squads, memberships, ownership, and planned capacity. |
| **Workspace** under ENGINEERING | Opens the Engineering workspace to run and inspect tasks. |
| **Models** under SYSTEM | Configures provider connections and the AI model route. |
| Project name under LOCAL PROJECTS | Selects that project and opens its Planning view. This list appears when the sidebar is expanded. |
| Top breadcrumb | Shows your current section, or the selected Engineering project's name and task key. |
| Connected / Backend offline | Reports connection to the backend, not whether the AI provider is healthy. It can be hidden at narrower widths. |
| **T** avatar | Shows local workspace information. It is not a sign-in or account-switch button. |
| **×** on a notification | Dismisses the visible notification; it does not fix or erase the underlying failure. |

Board uses its own toolbar, so its page header looks different. The global sidebar arrow still works there.

Inside Engineering there is a **second left pane** showing tasks, workflow, or files. The pane-toggle button beside the Engineering tabs collapses this second pane only. It is separate from the global sidebar arrow.

**Navigation tips:** Scroll horizontally when the Board columns or Engineering tab row exceed the screen width. Switching tabs or refreshing does not start a new execution. Bookmarking an Engineering URL can preserve the selected task, tab, and historical run.

## 5. Models: connect the AI

Open **Models** in the global sidebar. This section answers two separate questions:

- **Connection:** which service should CodeOps contact?
- **Routing:** which connection and exact model ID should new operations use?

Saving a connection alone does not activate it. Finish with **Apply routing**.

### 5.1 Configure local Ollama, step by step

1. Ensure Ollama is running and the model you want is installed. This installation has used `qwen2.5-coder:3b`; the small model can still produce invalid or weak results.
2. Click **Add provider**.
3. Choose the **Local Ollama** preset.
4. Keep the connection name or give it a recognizable name.
5. Use **Ollama (local)** as the API protocol.
6. For a normal local installation, use `http://127.0.0.1:11434` as the API base URL. Ollama does not need an API key in this form.
7. Click **Save connection**.
8. Click **Test & load models** on the saved card.
9. Under **Model routing → PRIMARY**, choose the connection.
10. Choose or type the **exact Model ID**, including its tag, such as `qwen2.5-coder:3b`.
11. Click **Apply routing**. Confirm that the **Active** notice names the connection and model you intended.

### 5.2 Configure a hosted or custom provider

1. Click **Add provider** and choose NVIDIA NIM, OpenAI, Anthropic, Google Gemini, or Custom provider.
2. Enter the connection name, supported protocol, provider's API base URL, and API key where required.
3. Click **Save connection**, then **Test & load models**.
4. Select that connection and model under PRIMARY, then **Apply routing**.

Custom provider means an endpoint implementing one of the supported protocols. It does not make every arbitrary AI service compatible. Saved API keys cannot be viewed through the form; leaving a key blank while editing preserves the saved key unless you select **Remove saved key**.

### 5.3 Every Models control

| Control | What it does |
| --- | --- |
| **Refresh** | Reloads saved settings and active routing. Unsaved routing selections can be replaced by the saved values. |
| **Add provider** | Opens a new connection form. |
| **Provider preset** | Fills example values. Changing it resets the new connection form to that preset. |
| **Connection name** | Your label for a service; it is not the model ID. |
| **API protocol / API base URL** | Tell CodeOps how and where to contact the service. |
| **API key** | Sets or replaces the credential for a non-Ollama provider. |
| **Remove saved key** | Requests removal of the credential when you save the edited connection. |
| **Advanced compatibility** | Expands provider-specific options: structured JSON format, token-limit parameter, and whether to send temperature. Use these to match the selected provider's API. |
| **Save connection** | Saves the provider details. Does not apply a model route. |
| **Cancel / ×** in the provider form | Closes the form without saving its edits. |
| **Test & load models** | Checks connectivity and credentials and requests a model list. It does not generate text or prove the model can complete a task. |
| Pencil icon / **Edit [name]** | Opens an existing connection for editing. |
| Trash icon / **Delete [name]** | Removes an unused connection. It is disabled if saved primary or fallback routing references it. There is no second confirmation dialog in this UI. |
| **Connection / Model ID** in routing | Select the service and exact model for primary or fallback use. |
| **Load models** in routing | Fetches a catalog for the currently selected connection. You can also type an exact ID manually. |
| **Reasoning** in an NVIDIA provider form | Sets Provider default, Disabled, Enabled (Laguna), Low, Medium, or High for this saved connection. Supported values depend on the exact model; see [NVIDIA compatibility](provider-settings.md#nvidia-reasoning-compatibility). Laguna structured requests default to Disabled; Kimi retains Low. |
| **Test selected model** in routing | Runs one optional tiny JSON generation check against the selected saved connection/model: 32 output tokens, 25-second timeout, no repository content, and no fallback. Its result is separate from catalog connectivity; passing does not guarantee large tasks succeed. |
| Effective reasoning / primary timeout notice | Explains any compatibility default and the configured wait before eligible fallback. A 600-second operator timeout can mean ten minutes before fallback; this is not changed by the UI check. |
| **Enable fallback** | Allows an optional second route for connection, timeout, rate-limit, or availability failures. Invalid generated results and rejected code reviews do not trigger provider switching. |
| **Apply routing** | Activates the selection for new operations. An operation already running keeps its current model. |
| **Use environment settings** | Removes the saved route override and restores the environment-based configuration. |

If settings are locked, the interface shows a notice and configuration must be handled by the operator responsible for the environment. See [provider settings](provider-settings.md) for setup details.

## 6. Projects: add your code

You need the **source application folder**, not the folder where CodeOps stores its execution copies. For an exercise, use a separate demo project rather than accidentally asking agents to edit CodeOps itself.

1. Open **Projects**.
2. Click **Add project**.
3. Enter a recognizable **Project name**.
4. Enter the absolute **Repository path**, for example `C:\Users\tahab\Desktop\My Project\imported\my-demo`.
5. Click **Add project** in the dialog. **Adding…** means registration is in progress.
6. Click its project row whenever you want to select it and open Planning.

The path must be inside the configured `ASE_REPOSITORY_ROOT` and outside `ASE_WORKSPACE_ROOT`. If the folder is rejected, ask the local operator to check that configuration; do not select an unrelated folder just to bypass the error.

| Control | What it does |
| --- | --- |
| **Add project** on the page | Opens the local-project registration form. |
| **Project name / Repository path** | Set the display name and source folder. |
| **Add project** in the form | Registers that source folder and selects the new project. |
| **Cancel / ×** in the form | Closes the form without registering. |
| Project row / right arrow | Selects the project and opens Planning. |
| **Preview settings for [project]** | Configures how this project's generated result can run in a temporary preview. It does not start a preview. |

**GitHub note:** this Projects screen currently registers local folders. There is no visible GitHub import button here. GitHub-backed import and delivery require the existing backend setup; ask the operator to follow the [platform runbook](platform.md#tests-and-delivery). Simply adding a folder cloned from GitHub does not necessarily configure CodeOps's GitHub delivery metadata.

## 7. Planning: turn an idea into approved tasks

### 7.1 Generate a product draft

1. Open **Planning** and check the **Project** selector.
2. In **What do you want the team to build?**, describe a small, concrete outcome.
3. Include relevant existing files or behavior when you know them. Example:

   > Improve the existing greeting function to trim whitespace around the name. Preserve the Hello prefix and add a test for a padded name.

4. Click **Plan with CodeOps**.
5. Wait for Queued / Planning / analysis to finish. Keep the worker and model service running. You can refresh while the request is saved.
6. Read the returned draft and its **Planning basis**.

**Repository-grounded** means CodeOps used observed repository information. **Goal-only** means repository inspection was unavailable or insufficient; read the stated reason. Inspection is bounded, so it does not imply every file was read.

### 7.2 Edit and approve

1. Read the plan title, summary, epics, task descriptions, estimates, dependencies, and acceptance criteria.
2. Correct proposed work that does not fit the repository or goal.
3. Use **Save changes** after editing. Wait for the saved revision.
4. Click **Approve Plan & Create Work Items** only when the saved draft is ready.
5. The approved tasks receive permanent `CO-…` keys and become available in Board, Teams, and Engineering.
6. Click **Open board** to see them.

This approval creates work items. It does **not** approve a coding execution or start an AI developer.

### 7.3 Every Planning control

| Control | What it does |
| --- | --- |
| **Project** selector | Changes which project's goals and plans you are viewing. |
| Goal text area | Defines the next product-planning request. |
| **Plan with CodeOps** | Submits a new goal for generation. Repeating it creates another saved plan rather than overwriting approved work. |
| **Saved plans** selector | Opens an earlier saved plan when several exist. It does not rerun that plan. Save draft edits before switching away. |
| **Inspected files / Inspection limits** | Expands the repository observations and the limits of the planning context. |
| **Plan title / Plan summary** | Edits the draft's overall description. |
| Epic title / description | Edits a group of proposed work. |
| Task's expandable heading | Shows or hides that draft task's editor. |
| Task title / description | Edits the intended change. |
| **Epic** selector in a task | Moves that task to another epic in this draft. |
| **Priority** | Sets low, medium, high, or urgent. |
| **Estimate (hours)** | Sets rough effort in quarter-hour increments, from 0.25 to 24 hours per draft task. It is not a delivery promise. |
| **Technical area** | Chooses the skill area used when considering ownership. |
| **Dependencies** | Chooses prerequisite draft tasks. Hold Ctrl on Windows or Cmd on macOS to select multiple entries. Do not create circular dependencies. |
| **Acceptance criteria (one per line)** | Edits observable requirements for that task. |
| **Add task to E…** | Adds a proposed task under that epic. |
| **Delete task** | Removes it from the current draft and removes references to it from other draft dependencies. |
| **Delete epic and its tasks** | Removes that entire proposed group, including its tasks. |
| **Add epic with task** | Creates a new epic with a starter task. Drafts support up to 8 epics and 32 tasks. |
| **Assumptions (one per line)** | Records assumptions the plan depends on. |
| **Save changes** | Persists edited draft content and advances its revision. Disabled when there is nothing to save or the draft has no epics/tasks. |
| **Reload saved draft** | Fetches the saved version after an error. Local unsaved edits may be lost; copy important edits before reloading. |
| **Approve Plan & Create Work Items** | Approves the exact saved draft and creates actionable tasks. Disabled while edits are unsaved or the draft is empty. |
| **Open board** | Opens approved work for the selected project. |
| **Planning model log** | Expands recorded provider/model information where retained. |
| Approved task row under an epic | Opens its task-detail dialog, with the same controls described in Board. |
| **Planning assumptions · N** | Expands the approved plan's saved assumptions. |

Draft deletions stay local until **Save changes**. Navigating away or reloading can lose unsaved edits. Once a plan is approved, this screen presents its saved result rather than the editable draft form. Older approved tasks remain on the Board when you generate another plan.

## 8. Board: see and open the work

The Board contains approved tasks for the selected project, including work from earlier approved plans. Unapproved draft tasks do not appear here.

| Column | Meaning |
| --- | --- |
| Backlog | Work recorded for later consideration. |
| Planned | Work prepared for execution. |
| In progress | Work underway. |
| Review | Work awaiting review; linked successful executions wait for a human decision here. |
| Done | Work marked complete. For linked executions, human acceptance governs completion. |

1. Open **Board** and choose the correct project.
2. Scroll horizontally to view the columns if needed.
3. Click a task title/card to open its details.
4. Review the description, dependencies, acceptance criteria, and owner.
5. Assign the task or click **Open engineering workspace** to work on it.

| Control | What it does |
| --- | --- |
| **Project** selector | Changes the project's Board. |
| **Go to planning** on an empty Board | Opens Planning so you can generate or approve work. |
| **Filter** | Shows or hides Search tasks, Priority, Area, Assignee, and Squad filters. |
| **Search tasks** | Filters by title, key, or description. |
| Priority / Area / Assignee / Squad filters | Narrow visible cards; they do not change tasks. |
| **Clear filters** | Resets these filters. |
| Task title/card | Opens task details; it does not start execution. |
| Status dropdown on a card | Changes status for unlinked tasks when allowed. Moving an unimplemented task to Done does not implement it. |
| Priority bars / area label / clock estimate / owner | Display information, rather than starting actions. |
| **×** in task details | Closes the detail dialog. |
| **Status** in task details | Changes an unlinked task's Board status. Linked task status follows execution and acceptance, so this field becomes disabled. |
| Dependency button | Opens the referenced task's details. |
| **Open engineering workspace** | Opens the selected task in Engineering. Depending on its state the label becomes **Review implementation plan** or **Review implementation result**. |

The **Assignment** controls in task details are explained below. This Board uses cards and status selectors; do not assume drag-and-drop status changes are implemented.

## 9. Teams: create members and assign ownership

Teams has two tabs. **Workspace members** are shared identities across projects. **Project teams** describes which of those identities participates in the selected project and squad.

A member is an ownership/configuration record. Creating a human member does not invite someone or give them an account. Creating an AI member does not install a model; model routing is configured separately in Models.

### 9.1 Create an AI developer

1. Open **Teams → Workspace members**.
2. Click **New workspace member**.
3. Enter a **Name**, such as “Backend Agent,” and a **Role** description.
4. Choose **Member type → AI**.
5. Set **Availability → Available**.
6. Set **Maximum concurrent executions** to the intended runtime limit, such as 1.
7. Set **Future execution role → developer**. Despite the word “Future,” this value is used to identify eligible AI developers for current execution.
8. Check the relevant skill, such as Backend, and choose a proficiency from 1 to 5.
9. Keep **Active member** checked.
10. Click **Save member**.

### 9.2 Add that member to a project

1. Choose the target project at the top of Teams.
2. Open **Project teams**.
3. Click **New squad**, enter its name and description, select technical areas, and **Save squad**.
4. Click **Add existing member**.
5. Select your **Workspace member** and its **Primary squad in this project**.
6. Keep **Active project membership** checked and **Save membership**.

Reuse the same workspace identity in multiple projects when appropriate. It can have one primary squad per project membership.

### 9.3 Assign a task

1. Open its details from Board or Teams, or open Engineering → Overview.
2. In **Assignment**, choose a **Squad** and **Assignee**. Engineering's execution-oriented editor labels the assignee **AI developer** and filters accordingly.
3. Click **Save assignment**.
4. If warnings appear, read them. Correct the issue where possible. **Assign despite these warnings** is an explicit override of assignment warnings; it does not bypass execution eligibility checks.
5. Open Engineering and inspect **Readiness** before starting the task.

### 9.4 Every Teams and Assignment control

| Control | What it does |
| --- | --- |
| **Workspace members / Project teams** | Switches between shared identities and project-specific squads/memberships. |
| **Project** selector | Changes the project context, especially for Project teams and assignment suggestions. |
| **New workspace member** | Opens the shared identity form. |
| **Edit [member name]** | Changes shared name, role, skills, activity, or resource configuration across projects. Member type is fixed after creation. |
| **Weekly capacity (hours)** for humans | Sets a planning budget, not tracked work time. |
| **Target utilization (%)** for humans | Defines how much of that budget is assignable; the rest is reserved. |
| **Availability** for AI | Sets available, busy, or offline planning availability. It is manually configured. |
| **Maximum concurrent executions** for AI | Sets the limit on actual reserved/running executions, not the number of owned tasks. |
| **Future execution role** for AI | Sets developer, tester, reviewer, or general. An AI developer is needed to start the linked coding workflow. This does not select a separate per-agent model. |
| Skill checkbox / proficiency selector | Adds an area and your manually assessed level from 1/5 to 5/5. |
| **Active member** | Enables/disables a shared identity for new participation; historical ownership remains recorded. |
| **Save member** | Saves the identity. At least one skill is needed. |
| **New squad / Edit squad / Save squad** | Creates or edits a project squad's name, description, and technical areas. |
| **Add existing member** | Adds a workspace identity to this project. Requires a squad and an identity not already a member of this project. |
| **Edit membership for [name]** | Changes that project's primary squad or active membership. Moving squads also moves that member's assignments in that project. |
| **Save membership** | Saves project participation; it does not edit shared skills or capacity. |
| **× / Escape** in the team editor | Closes the form without submitting unsaved edits. |
| Task under **Active work**, **Currently running / reserved**, or expanded assigned tasks | Opens the task detail dialog. |
| **… assigned tasks not Done** | Expands the member's outstanding tasks. |
| **Assign / recommendations** | Opens a task so you can assign it or inspect recommendations. |
| **Recommend assignments** | Builds a proposed batch for unassigned work in the current project plan. It does not save ownership yet. |
| **Apply N suggested assignments** | Saves the displayed proposal after backend checks. It does not start those tasks. |
| **Dismiss suggestions** | Closes the proposal without applying it. |
| **Refresh teams** | Reloads resources after a displayed error. |
| **Squad / Assignee** in Assignment | Selects proposed ownership. Choosing a new squad clears the current unsaved assignee selection. |
| **Save assignment** | Persists ownership for the task. |
| **Remove assignment** | Clears the saved ownership when allowed. |
| **View recommendations** | Loads eligible candidate owners for an unassigned task. |
| **Select assignee** | Fills the suggested squad/member in the form. You must still click **Save assignment**. |
| **Assign despite these warnings** | Resubmits the assignment with explicit warning override; invalid/inactive membership or execution blockers may still prevent the action. |

**Human capacity example:** 30 weekly hours at 80% utilization gives 24 assignable hours and 6 reserved. All unfinished assigned work across projects contributes to the planned load. “Remaining” can become negative after a deliberate overload.

**AI capacity example:** an AI can own five unfinished tasks but have concurrency 1. Those five tasks are its queue of owned work; only an explicitly started run consumes the slot. Waiting for coding-plan approval also reserves a slot. Assignment is not automatic scheduling.

## 10. Engineering: run and inspect a task

### 10.1 Understand the layout

Open **Workspace** under ENGINEERING, or use the task-detail handoff button.

1. **Global sidebar:** main navigation and its top arrow.
2. **Engineering navigator:** task browser or context for the selected task.
3. **Task header:** title, key, area, AI owner, run, state, and available actions.
4. **Tab row:** Overview, Plan, Files, Diff, Tests, Review, Acceptance, Preview, History.
5. **Main pane:** the selected tab's content.

CodeOps may restore your last selected task. **Back to tasks** exposes the browser without discarding the selected task's main view.

### 10.2 Task browser controls

| Control | What it does |
| --- | --- |
| **All** | Shows engineering work across statuses. |
| **Active** | Filters for active executions, including queued/approval-waiting work treated as active by the execution system. |
| **Review** above the task list | Filters tasks waiting for human review. This is different from the main **Review** tab, which shows AI findings. |
| **Done** | Filters completed work. |
| **History** above the task list | Lists retained runs for historical inspection. This differs from the main History tab for the selected task. |
| Circular arrow / **Refresh engineering tasks** | Reloads the task inventory and history listing. |
| **Search work…** | Filters tasks by key/title; standalone runs use their request text. |
| **All projects** selector | Filters the navigator by project. |
| **All statuses** selector | Filters by Board status. |
| Task or run row | Opens that work and its appropriate available tab. Historical rows open read-only inspection. |
| **Show all engineering work** | Returns from an empty mode to All; separately clear any search/project/status filters if still needed. |
| **Back to tasks** | Switches the secondary pane from the selected task's context to discovery/search. |
| **Collapse workspace pane / Expand workspace pane** beside the tabs | Hides/shows this secondary pane. It does not collapse the global sidebar or change the selected task. |
| **Metrics** in historical navigation | Opens the recorded evaluation endpoint in another tab. It is an inspection link, not a run button. |

### 10.3 Start a run

1. Select an approved task.
2. Open **Overview** and read its description, requirements, dependencies, assignment, and readiness.
3. If needed, use **Assign AI developer** and save ownership.
4. Resolve dependencies and any other displayed blockers.
5. Click **Run with CodeOps** in the header.
6. Wait while CodeOps creates a snapshot and analyzes the repository.
7. When the task shows **Plan approval**, inspect **Plan**.
8. Choose the test runner, framework, and maximum attempts. Click **Approve & continue** only after reviewing the file scope.
9. Wait for development, tests, AI review, and evidence. Inspect progress in **History**.
10. When the task reaches human Review, inspect the result before accepting or requesting changes.

### 10.4 Header actions and state

The interface shows actions relevant to the current state. Seeing fewer buttons early in a task is normal.

| Button / state | Meaning and next step |
| --- | --- |
| **Assign AI developer** / Unassigned | Opens/focuses assignment in Overview. A human owner or a non-developer AI does not satisfy the linked coding workflow. |
| **Run with CodeOps** / Ready | Starts a new linked execution after backend eligibility checks. |
| Disabled **Run with CodeOps** / Blocked | Read readiness: check dependencies, active membership, AI availability, or reserved slots. |
| **Change assignment** | Opens the assignment editor when ownership needs attention. It does not resolve dependencies by itself. |
| **Review plan** / Plan approval | Opens Plan; this button alone does not approve it. |
| **View execution** / work running | Opens History to inspect operations. |
| **Cancel execution** | Requests cancellation. Wait for the worker to record cancellation before reassigning or retrying. |
| **Accept result** / human Review | Opens the human acceptance dialog; final acceptance requires submitting it. |
| **Request changes** | Opens a feedback form for a fresh corrective run when allowed. |
| **Retry with CodeOps** / failed or cancelled task | Starts a new linked run if eligible. Diagnose the failure first. |
| **Retry as new run** | Retries a standalone execution that is not linked to an approved EngineeringTask. |
| Circular arrow / **Refresh selected engineering task** | Reloads the selected task/run and inventory. It does not retry or clear errors. |
| **Create commit / Apply locally / Create draft PR** | Delivery actions; see section 13 before using them. |
| **Historical** | Read-only inspection. Current execution decisions and delivery actions are hidden. |

The workflow rail shows Analyze → Plan → Human approval → Develop → Tests → AI review → Acceptance evidence → Human review. Clicking a stage navigates to its relevant evidence; it does not run or complete that stage. “Not recorded” means no completion was retained, not that the stage passed.

## 11. Every Engineering tab

Tabs become available as evidence is recorded. Hover over an unavailable tab for its reason. If a saved tab is unavailable for the selected task, CodeOps can return to Overview. Left/Right arrows, Home, and End navigate available tabs when the tab row has keyboard focus.

### 11.1 Overview

**Purpose:** understand what this task wants and what to do next.

Before execution, read the description, acceptance requirements, dependency statuses, assignment, and readiness. During execution, read current operation and recent events. After execution, read change/test/review summaries, recorded errors, and the report.

| Control | Action |
| --- | --- |
| **Assign AI developer / Change assignment** | Opens/focuses the editor described in Teams. |
| **Review plan** | Opens the coding plan while approval is waiting. |
| **Execution history** | Opens recorded operations to diagnose failure. |
| Changes / Tests / AI review / Acceptance / Preview summary card | Opens the corresponding tab if available. These are shortcuts, not verification actions. |
| **Repository analysis · N files inspected** | Expands retained languages, frameworks, architecture, relevant files, and limitations. |

### 11.2 Plan

**Purpose:** inspect and approve the coding plan for this specific run. This is different from the product draft in Planning.

Read the problem interpretation, numbered steps, intended files, planned validation, and risks. A plan proposing the wrong folder, unsupported scope, or irrelevant work should not be approved. Cancel and correct the task/source/model setup before making a fresh run if necessary; this tab is not a free-form plan editor.

| Control | Action |
| --- | --- |
| Numbered step in the secondary pane | Scrolls to that step in the main document. |
| **Test runner → Docker** | Runs validation in the configured container environment. Docker and its runner image must be ready. |
| **Test runner → Trusted local** | Runs allowed Python validation locally. Use only for code you trust; it is not container isolation. |
| **Framework** | Selects unittest, pytest, or npm to fit the project. npm is unavailable with Trusted local. |
| **Maximum attempts** | Sets the bounded execution/repair attempt limit from 1 to 5. It does not promise that every model failure will be retried. |
| **Approve & continue** | Authorizes edits in the isolated snapshot and subsequent execution. Available only for the current waiting approval. |
| **Repository context files** | Expands filenames supplied as coding context. |
| **Risks and limitations** | Expands the retained cautions. |

A numbered plan is intended work, not a checked-off record of individual step completion. A failed/cancelled run can still display its retained plan without an approval button.

### 11.3 Files

**Purpose:** read the resulting snapshot files. This is a read-only viewer, not an editor.

- Select a changed file in the secondary pane. **A** means added, **M** modified, and **D** deleted.
- Read the highlighted source and line numbers.
- Click **View diff** to compare it with the original version.
- A deleted file has no resulting source; inspect its Diff instead.
- A review finding may open referenced source even when that reference is not among the changed files.

Available after retained changes exist. The files shown belong to the selected run; viewing them does not apply them to the original repository.

### 11.4 Diff

**Purpose:** inspect exactly what changed.

Select a file in the secondary pane. Added lines have a plus sign; removed lines have a minus sign. Context lines show unchanged surrounding code. Old/new line numbers identify each side of the change.

| Control | Action |
| --- | --- |
| Changed-file row | Selects that file's retained changes. |
| **Copy path** | Copies the selected file path, not its contents. Shows Copied after success. |
| **Download diff** | Downloads the retained run diff as a text artifact; the diff can contain changes for multiple files. This is not the complete source/Git export. |
| **Unified** | Shows old and new changes in one sequence. |
| **Split** | Shows the comparison side by side. |
| **Collapse file / Expand file** | Hides/shows the displayed diff body. |
| **Show more lines · N remaining** | Loads additional retained lines; the viewer initially limits a large file to 500 lines. |

Color highlighting helps you read code; it does not prove correctness. If there is no retained text hunk, the viewer says so rather than inventing a comparison.

### 11.5 Tests

**Purpose:** inspect validation that actually ran.

Read outcome, reported counts when available, command, exit status, duration, and execution errors. A zero exit code does not guarantee the tests cover your requirements. Missing individual counts are shown as unknown rather than guessed.

- A test command in the secondary pane scrolls to that execution record.
- **Output / logs** expands its retained output.
- “Timed out” or “Execution error” needs investigation even if the implementation looks plausible.

The tab becomes available when test execution starts or a result exists. You do not launch a separate test rerun from this tab; test settings are selected at coding-plan approval.

### 11.6 Review

**Purpose:** read the AI review of the generated result. It does not replace your review.

The screen shows Approved or Changes required, a summary, and findings. Findings may include severity, file/line, evidence, and a recommended fix.

- A finding in the secondary pane scrolls to its main entry.
- A linked **file:line** opens the corresponding Diff or source view. Inspect the reference rather than assuming the AI comment is accurate.

The tab becomes available when review starts or a result is retained. A reviewer approval does not mark a linked task Done. A rejection can lead to a bounded repair attempt; an exhausted or invalid run can finish Failed.

### 11.7 Acceptance

**Purpose:** compare the requirements with retained evidence before your final decision.

Before a run, this tab shows requirements. After a run, it can show evidence waiting, processing, ready, unavailable, or not generated.

| Label | What it means |
| --- | --- |
| **Verified by passing test evidence** | A retained passing check was mapped to the criterion. Inspect whether that check truly covers what you need. |
| **Supported by implementation evidence** | Retained implementation or other evidence supports it, but there is no directly mapped passing check verifying it. |
| **Not automatically verified** | No adequate automatic verification was mapped. Human inspection is required. |
| **Conflict — human review required** | Conflicting/negative evidence needs your attention. |
| **Processing** | Mapping is unfinished; acceptance waits for pending evidence to finish. |
| **Unavailable / Not generated** | No completed mapping is available. Inspect raw artifacts and acknowledge unresolved evidence if you choose to accept. |

**View test**, **View AI review**, and **View diff** open the underlying evidence. **Full source summary** expands a long evidence description. An AI association supports a criterion; it is not itself a passing test.

Acceptance evidence does not accept the task for you. Use the header's **Accept result** or **Request changes** after inspection.

### 11.8 Preview

**Purpose:** run the generated application temporarily and inspect it yourself.

A new preview needs the current linked successful execution awaiting human acceptance, a valid enabled project preview profile, Docker, the relevant image, and the preview worker. Start it before accepting the result. The tab can remain available afterward for inspecting records even when a new start is no longer allowed. Standalone/older runs may have different availability. Historical preview inspection shows retained attempts rather than starting a new environment.

1. Click **Preview settings** if configuration is missing or unsuitable.
2. Click **Start Preview** or **Start API Preview**.
3. Wait for queued → building → starting → ready. Read failures/logs if it stops.
4. Click **Open Preview**, **Open API**, or **Open API Docs**, as offered.
5. Exercise the acceptance requirements, including invalid input and error paths.
6. Stop the preview when finished.

| Control | Action |
| --- | --- |
| **Start Preview / Start API Preview** | Requests a temporary container for the selected result. It does not deploy the app. |
| **Open Preview** | Opens the temporary web/static application's URL. |
| **Open API** | Opens the API preview's base URL. |
| **Open API Docs** | Opens its configured documentation/open path when offered. |
| **Stop Preview** | Requests cleanup; wait for the worker to confirm stopping. |
| **Restart** | Stops the current environment, waits for cleanup, then requests a new preview when eligible. Temporary runtime data can be lost. |
| **Preview settings** | Opens the project profile editor. |
| **Preview logs · bounded tail** | Expands the retained recent output, not an unlimited complete log. |
| **Preview history · N attempts / Logs** | Expands previous preview attempts and their retained output. |
| **Retained logs** in historical Preview | Shows output for that historical attempt; the old URL may no longer be live. |

Previews expire after their configured lifetime. Opening a preview does not automatically verify a criterion or accept the result.

### 11.9 History

**Purpose:** explain what happened and compare attempts.

Read run number, phase, human review state, creation time, feedback, and the selected run's operation timeline. Each operation may include status, duration, attempt number, error code/message, and model information.

| Control | Action |
| --- | --- |
| Run row in **Execution attempts** | Selects that retained run for read-only inspection. |
| **Inspect this run** | Opens that run while preserving recorded artifacts. Inspection is read-only, even if you selected the current run through History. |
| **Inspect diff / Inspect tests** | Opens the selected run's corresponding available artifact tab. |
| Saved delivery record heading | Expands its stored receipt or delivery error details. |
| **Back to tasks**, then choose the normal task from **All** | Returns to the current actionable task context after historical inspection. |

Model entries identify provider, model, purpose, outcome, latency, token counts when reported, and fallback use. Empty/missing counts do not mean zero tokens were used.

## 12. Preview settings: configure how your app runs

Open **Projects → Preview settings for [project]**, or **Engineering → Preview → Preview settings**.

This is the most technical form. If you do not know the application's start command, ask its developer to configure it. Example buttons fill templates, not guaranteed working settings for every project.

| Field / button | Meaning |
| --- | --- |
| **Vite example / FastAPI example / Static example** | Fills sample runtime, commands, port, and paths. Adjust them to the actual project's scripts/module names. |
| **Enabled** | Allows use of this profile when execution is eligible. |
| **Name** | Your label for the profile. |
| **Type** | `web`, `api`, `static`, or `none`, describing the application experience. |
| **Runtime** | Python or Node container runtime. |
| **Build commands · JSON argv arrays** | A list of commands, each expressed as a list of separate arguments. `[]` means no build commands. |
| **Start command · JSON argv array** | The application's process and separate arguments, such as `["python", "app.py"]`. This is not a free-form shell command. |
| **Container port** | The port the application listens on inside the container; CodeOps manages its temporary host URL. |
| **Timeout · seconds** | Startup/build timeout setting. |
| **TTL · minutes** | How long the temporary preview is retained before expiry/cleanup. |
| **Health path** | HTTP path checked to decide whether the preview is ready, such as `/health`. |
| **Open path** | The path opened for inspection, such as `/` or `/docs`. |
| **Non-secret environment** | One `NAME=value` entry per line. Do not put credentials here. |
| **Allow network during dependency preparation/build** | Allows network access during preparation/build. Runtime outbound connections remain blocked. |
| **Requires external services** | Declares that the app needs external services; such previews are unsupported in v1. It does not provision a database. |
| **Validate** | Checks the configuration's shape/constraints. Does not launch the application or verify startup. |
| **Save** | Persists the profile. Does not run commands or start a preview. |
| **×** | Closes the settings dialog; save first if you want to keep edits. |

For a simple Python app using `app.py`, an example is:

```text
Enabled: yes
Type: web
Runtime: python
Build commands: []
Start command: ["python", "app.py"]
Container port: 8000
Health path: /health
Open path: /
Requires external services: no
```

Use these values only if that application's actual behavior matches them. Containerized preview dependencies use `requirements.txt` for Python and `npm ci` with `package-lock.json` for Node. The generated application's server must listen on a container-accessible address such as `0.0.0.0`. See [local previews](local-previews.md) for image and dependency requirements.

## 13. Accept, request changes, and deliver

### 13.1 Accept a satisfactory result

1. Make sure you are viewing the current run, not historical inspection.
2. Read Diff, Tests, Review, and Acceptance. Use Preview when applicable.
3. Click **Accept result** in the header.
4. If offered, deliberately check **I reviewed unresolved criteria, conflicts, and any unavailable evidence** after investigating those items. Do not treat it as a routine checkbox to skip.
5. Click **Accept result** in the dialog.
6. CodeOps stops any active preview for that run before completing acceptance. If cleanup is pending, let the preview worker finish and retry the decision.
7. The linked task becomes Done with recorded human acceptance.

**Cancel / ×** closes the human-review dialog without deciding. Acceptance does not automatically change the original repository, create a PR, merge code, or deploy anything.

### 13.2 Request a correction

1. Click **Request changes** when offered for the current result.
2. Explain the specific correction in **Feedback**. Example: “Reuse the existing email validation helper and add a duplicate-email test.”
3. Submit **Request changes** in the dialog.
4. A new execution is created, and the previous run remains in History.
5. Review and approve the new coding plan. Inspect its new result when complete.

The fresh run starts from registered source plus retained feedback/context. It does not automatically adopt every generated file from the preceding snapshot. Make the request clear about the intended complete outcome and compare runs when necessary.

### 13.3 Deliver the accepted code

Choose one of the header's available delivery actions. A successful standalone execution can expose delivery without the linked-task acceptance journey; the recommended beginner workflow uses approved linked tasks and human acceptance.

| Action | What happens | Changes the original source? |
| --- | --- | --- |
| **Create commit** | Creates/downloads an independent Git repository export containing baseline and reviewed-change commits. The “commit” is an export, not an automatic commit in your source folder. | No. |
| **Apply locally** | Writes the reviewed changes into the original registered source after safety checks. Conflicting source changes can cause refusal. | **Yes.** |
| **Create draft PR** | Publishes reviewed changes to a dedicated GitHub branch and opens a draft pull request for an imported/configured GitHub project. Requires credentials and metadata. | Does not merge the original branch automatically. |

Each action first opens a confirmation dialog listing affected files and the destination/purpose.

- **Cancel:** close without delivering.
- **Confirm commit export:** produce the export.
- **Confirm source changes:** write the reviewed changes locally.
- **Confirm draft PR publication:** publish the branch and draft PR.

Inspect the file list before confirming. Successful deliveries retain a receipt in History and their buttons can become disabled to avoid repeating them. Check History for `last_error` if a delivery fails.

Do not confuse “I exported the code” with “my original app now contains it.” After local apply, independently run/check the source app as appropriate. A PR still needs its normal review and merge outside this local workflow.

## 14. A first task from start to finish

Use a separate disposable demo folder containing known source and tests. The [v1 demo](v1-demo.md) explains copying `examples/developer-demo` to a fresh source folder. Do not overwrite an existing demo or use the CodeOps application's own folder as the exercise target.

1. Start the API and worker; start the preview worker and Docker if you want previews.
2. Open **Models** and confirm an active route. Test/load the connection if uncertain.
3. Open **Projects → Add project** and register the demo's absolute source path.
4. Open **Planning** and confirm that project is selected.
5. Enter a focused goal based on an existing file, such as trimming whitespace in the demo's `greeting.py` greeting function while preserving its Hello prefix.
6. Click **Plan with CodeOps** and wait for the draft.
7. Read the repository basis and every task. For this small exercise, keep the proposed work coherent and avoid unrelated changes.
8. Edit the draft if necessary and **Save changes**.
9. **Approve Plan & Create Work Items**.
10. Open **Teams → Workspace members**. Create/reuse an active, available AI member with **developer** execution role and a matching skill.
11. Open **Project teams** for the demo. Create a matching squad and **Add existing member**.
12. Open the approved task on **Board**. Select the squad and AI owner; **Save assignment**.
13. Click **Open engineering workspace**.
14. Read **Overview → Readiness**. Complete actual prerequisite work if blocked; do not mark unfinished dependencies Done merely to make the button work.
15. Click **Run with CodeOps**.
16. When approval is required, read **Plan**, including actual file paths. Reject/cancel an unsuitable proposal rather than approving obviously wrong scope.
17. Choose **Docker**, **unittest** for the Python unittest demo, and a bounded maximum such as 3. Click **Approve & continue**.
18. Watch the recorded operations in **History**. A model failure is possible; inspect the actual error before retrying.
19. On success, read **Files**, **Diff**, **Tests**, **Review**, and **Acceptance**.
20. For a greeting-only change, source and test inspection can be more useful than a web preview. For a web/API task, configure and start Preview and check the required behavior.
21. If dissatisfied, **Request changes** with concrete feedback and inspect the fresh run. Otherwise **Accept result**.
22. Choose **Create commit** for an export, or another explicitly configured delivery action. Review the confirmation before proceeding.
23. Open **History** later to inspect the run and delivery record.

For a longer registration/API exercise with exact preview checks, follow [the complete v1 demo](v1-demo.md). Model-generated task numbers and paths can vary; follow the actual retained plan, not a promised `CO-1` or fixed run count.

## 15. Troubleshooting and disabled buttons

| What you see | What to do |
| --- | --- |
| Browser cannot open CodeOps | Start the API and use `/ui/` on port 8765. Check the API terminal for its actual error. |
| `/health` works but `/` returns 404 | The health endpoint is not the interface. Open `http://127.0.0.1:8765/ui/`. A favicon 404 alone does not explain a failed coding run. |
| UI loads but planning stays queued | Check that the worker is running, then inspect its terminal and configured model service. |
| Backend offline | Confirm the API is running and refresh. This differs from a provider connection failure. |
| Add project rejects the path | Verify the folder exists and is inside the allowed repository root, outside the execution workspace root. |
| Provider catalog fails | Check protocol, base URL, provider credentials, and whether the local/remote service is reachable. |
| Model list loads but generation fails | Connectivity succeeded; structured generation did not necessarily succeed. Inspect the task error and model trace. |
| Product plan is Draft but Board is empty | Save edits, then approve the product draft. Draft tasks stay out of actionable views. Also check the selected project. |
| **Save changes** disabled | Nothing changed, the editor is busy, or the draft has no epics/tasks. |
| Product approval disabled | Save unsaved edits first; retain a nonempty valid draft and resolve its validation errors. |
| **Save member** disabled | Add at least one skill and complete required fields; wait if saving is in progress. |
| **Add existing member** disabled | Create a squad and a workspace identity not already joined to this project. |
| No eligible AI developer in Assignment | Create an AI identity with developer role, then add an active project membership. Check the selected squad. |
| Task assigned but nothing runs | Assignment only records ownership. Open Engineering and explicitly start it. |
| Run blocked by dependencies | Open the prerequisite tasks and complete their real work. Their Done status is required for eligibility. |
| AI at execution capacity | Inspect its active/reserved runs. A coding plan awaiting approval can occupy the slot; finish or cancel that run deliberately. |
| Assignment/status controls disabled | Active execution locks ownership; linked execution controls its task status. Use the proper Engineering workflow instead. |
| Plan exists but no **Approve & continue** | The selected run is not currently awaiting approval, or you are in historical inspection. Check its phase and return to current work. |
| Files/Diff/Tests/Review unavailable | The relevant artifact/stage has not been recorded. Hover for the tab's reason and inspect History. |
| `INVALID_DEVELOPMENT` | The model did not return a complete valid development result. Inspect History and the coding plan; improve the model/task scope before explicit retry. |
| `INVALID_EDIT` | Generated edits were invalid, for example wrong created/modified kind or no actual file change. Inspect source, approved scope, and the recorded message. |
| `DEVELOPMENT_SCOPE` | Generated paths failed approved-plan scope checks, such as an unapproved or repeated path. Review the real plan/error before retrying. |
| `REVIEW_REJECTED` | Read each finding and inspect the referenced code. It may repair within its attempt limit, or fail after rejection. An AI finding can itself be wrong. |
| Tests fail, time out, or cannot import dependencies | Open Tests → Output / logs. Check test framework, runner image, and project dependencies. Docker failure does not silently switch to local execution. |
| No human **Accept result** after failure | A failed run is not a completed reviewable result. Diagnose/retry eligible work; do not treat accepting as error dismissal. |
| Acceptance processing | Wait for evidence generation and keep the worker available. Pending evidence blocks the acceptance decision. |
| Acceptance has unverified/conflicting items | Inspect raw evidence and perform human checks. Request changes, or deliberately acknowledge unresolved evidence only if you decide it is acceptable. |
| **Start Preview** missing/disabled | Read the displayed eligibility reason. Check successful linked result, enabled supported profile, and selected current run. |
| Preview fails or never becomes ready | Check Docker Linux engine, preview worker/image, actual argv, app binding/port, health path, and logs. The run's code/test evidence remains available. |
| Preview stopping blocks acceptance/restart | Keep the preview worker and Docker running until cleanup is recorded, then retry. |
| Historical screen has no action buttons | It is read-only. Use Back to tasks → All and select the normal current task. |
| `409` / stale revision conflict | Another action/tab changed saved state. Reload the relevant resources, reconcile unsaved edits, and make the decision again. Recompute stale assignment suggestions. |
| **Create draft PR** absent | The source lacks required GitHub import metadata or credentials. Use commit export, or have the operator complete backend GitHub setup. |
| Apply locally refused because source changed | Review the original repository changes. Do not force an older snapshot over newer work; create/review fresh execution as appropriate. |

For failures, keep the task/run ID, error code/message, and relevant logs. These explain what failed without needing to delete saved state.

## 16. Daily checklist and current limits

### Before starting work

- Confirm API and worker are running.
- Confirm the active model route; keep its service available.
- Select the intended project.
- Check task dependencies, owner, and readiness.
- Review every coding plan before approval.

### Before accepting a result

- Read the diff and confirm the scope fits the task.
- Inspect test commands and results, not only the green label.
- Read AI findings and acceptance evidence.
- Try the application in Preview when appropriate.
- Make an explicit human decision, then a separate delivery decision.

### What the current system does not do for you

- It does not guarantee that an AI plan, generated change, or review comment is correct.
- It does not automatically schedule every owned task, resolve dependencies, or install your chosen model.
- It does not give workspace members login accounts or send invitations.
- It does not offer separate model routing for every agent through these controls.
- Estimates and capacity are planning information, not measured productivity or promised completion dates.
- It does not automatically accept work, merge PRs, or deploy applications.
- Previews are temporary single-container Python/Node environments, not persistent production hosting or external-service orchestration.
- Repository inspection is bounded and filtered; it is not a guarantee every source file or hardcoded secret was identified.

The current app is intended for one trusted local operator. Keep saved project state and run history when diagnosing work.

### More detail when you need it

- [Installation, prerequisites, and capabilities](../README.md)
- [Complete reproducible demo](v1-demo.md)
- [Provider settings](provider-settings.md)
- [Product planning](product-planning.md)
- [Teams and capacity](teams-and-capacity.md)
- [Task execution bridge](task-execution-bridge.md)
- [Preview configuration and images](local-previews.md)
- [Acceptance evidence](acceptance-evidence.md)
- [Operator runbook and delivery](platform.md)

This guide describes the interface in this checkout. Buttons depend on saved state, configuration, and available evidence, so every action will not be visible at once.
