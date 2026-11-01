import type { ApiTransport } from "../transport";

import type { EngineeringTask, ProductPlanDraft } from "../productTypes";

import type { ExecutionLink } from "../engineering/state";

import { previewFiles } from "../preview";

import * as fixture from "./data/fixtures";

/** Closed local router: unknown reads and mutations fail here, never fall back to HTTP. */

export function createShowcaseApi(): ApiTransport {
  const data = structuredClone({
    projects: fixture.projects,
    tasks: fixture.tasks,
    members: fixture.members,
    squads: fixture.squads,
    memberships: fixture.memberships,
    jobs: fixture.jobs,
    plans: [fixture.draftPlan, fixture.approvedPlan],
    profile: fixture.profile,
  });

  const decisions = new Map<string, string>();

  let sequence = 0;

  const reply = (value: unknown, status = 200) =>
    Response.json(value, { status });

  const unavailable = () =>
    reply(
      {
        detail:
          "Unavailable in the public showcase. Run CodeOps locally to use providers, repositories, execution or delivery. No external action was performed.",
      },
      403,
    );

  function workspace() {
    return {
      members: data.members,
      memberships: data.memberships,
      tasks: data.tasks,
      capacities: fixture.capacities(data.tasks),
      projects: data.projects,
      workspace_revision: 1,
    };
  }

  function teams(projectId: string) {
    return {
      ...workspace(),
      squads: data.squads.filter((s) => s.project_id === projectId),
      members: data.members,
      tasks: data.tasks.filter((t) => t.project_id === projectId),
      project_revision: 1,
      current_plan_id: "showcase-approved",
      workspace_members: data.members,
      workspace_memberships: data.memberships,
      workspace_tasks: data.tasks,
    };
  }

  function links(task: EngineeringTask): ExecutionLink[] {
    return data.jobs
      .filter((j) => j.engineering_origin?.engineering_task_id === task.id)
      .map((j) => ({
        execution_task_id: j.id,
        run_id: j.snapshot.run_id,
        ai_member_id: "agent-backend",
        phase: j.phase,
        node: j.node,
        review_state:
          decisions.get(j.id) ??
          (j.id.endsWith("previous")
            ? "changes_requested"
            : task.status === "done"
              ? "accepted"
              : "pending"),
        reviewed_at: null,
        created_at: fixture.date,
        feedback: j.id.endsWith("previous")
          ? "Illustrative retained feedback: add expired-token coverage."
          : null,
      }))
      .reverse();
  }

  return async (path, init) => {
    // Match HTTP's asynchronous task boundary so the existing session effects

    // can dispose a previous run's artifact request before a new one resolves.

    await new Promise((resolve) => setTimeout(resolve, 0));

    const url = new URL(path, "https://showcase.invalid");

    const parts = url.pathname.split("/").filter(Boolean);

    const method = init?.method ?? "GET";

    const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};

    const read = method === "GET";

    if (read && path === "/projects") return reply({ projects: data.projects });

    if (read && parts[0] === "tasks" && parts.length === 1)
      return reply({ tasks: data.jobs });

    if (read && path === "/evaluation")
      return reply({
        terminal_tasks: data.jobs.filter((j) =>
          ["succeeded", "failed", "cancelled"].includes(j.phase),
        ).length,
        successful_tasks: data.jobs.filter((j) => j.phase === "succeeded")
          .length,
      });

    if (read && path === "/system/status")
      return reply({
        database: "Illustrative in-memory data",
        model: "Showcase · no model calls",
        test_backend: "docker",
        github_configured: false,
        git_available: false,
        docker_available: false,
      });

    if (read && path === "/workspace/teams") return reply(workspace());

    if (parts[0] === "projects" && parts.length > 2) {
      const projectId = parts[1];

      if (read && parts[2] === "teams") return reply(teams(projectId));

      if (read && parts[2] === "engineering-tasks")
        return reply({
          tasks: data.tasks.filter((t) => t.project_id === projectId),
        });

      if (read && parts[2] === "plan")
        return reply(
          data.plans.find((p) => p.goal.project_id === projectId) ?? null,
        );

      if (parts[2] === "plans") {
        if (read)
          return reply({
            plans: data.plans.filter((p) => p.goal.project_id === projectId),
          });

        if (method === "POST") {
          const plan = structuredClone(fixture.draftPlan);

          plan.goal = {
            ...plan.goal,
            id: `showcase-draft-${++sequence}`,
            project_id: projectId,
            goal: body.goal,
          };

          data.plans.unshift(plan);
          return reply(plan);
        }
      }

      if (parts[2] === "preview-profile") {
        if (parts[3] === "validate")
          return reply({
            message:
              "Showcase configuration shape only. No commands or containers were run.",
          });

        if (method === "PUT")
          data.profile = {
            ...data.profile,
            ...body,
            revision: data.profile.revision + 1,
          };

        return reply({ ...data.profile, project_id: projectId });
      }
    }

    if (parts[0] === "product-plans") {
      const plan = data.plans.find((p) => p.goal.id === parts[1]);

      if (!plan) return reply({ detail: "Sample plan not found." }, 404);

      if (read) return reply(plan);

      if (parts[2] === "draft" && method === "PUT") {
        if (body.revision !== plan.draft_revision || plan.status !== "draft")
          return reply(
            { detail: "This sample draft changed. Reload it before saving." },
            409,
          );

        plan.draft = body.draft;
        plan.draft_revision = (plan.draft_revision ?? 0) + 1;
        return reply(plan);
      }

      if (
        parts[2] === "approve" &&
        method === "POST" &&
        plan.status === "draft" &&
        body.revision === plan.draft_revision
      ) {
        const draft = plan.draft!;

        const ids = Object.fromEntries(
          draft.tasks.map((t) => [t.ref, `showcase-created-${++sequence}`]),
        );

        const created: EngineeringTask[] = draft.tasks.map(
          (t: ProductPlanDraft["tasks"][number]) => ({
            ...t,
            id: ids[t.ref],
            key: `CO-${24 + sequence++}`,
            project_id: plan.goal.project_id,
            plan_id: plan.goal.id,
            epic_id: t.epic_ref,
            status: "backlog",
            revision: 1,
            dependencies: t.dependencies.map((ref) => ({ task_id: ids[ref] })),
            acceptance_criteria: t.acceptance_criteria.map((c, i) => ({
              ...c,
              id: `${ids[t.ref]}-${i}`,
            })),
            execution_run_id: null,
            squad_id: null,
            assignee_id: null,
            created_at: fixture.date,
          }),
        );

        data.tasks.push(...created);

        plan.status = "approved";
        plan.approved_at = fixture.date;

        plan.materialization = Object.fromEntries(
          draft.tasks.map((t, i) => [t.ref, created[i].key]),
        );

        plan.plan = {
          id: plan.goal.id,
          project_id: plan.goal.project_id,
          title: draft.title,
          summary: draft.summary,
          assumptions: draft.assumptions,
          epics: draft.epics.map((e) => ({
            id: e.ref,
            plan_id: plan.goal.id,
            title: e.title,
            description: e.description,
          })),
          tasks: created,
          estimated_hours: created.reduce(
            (sum, t) => sum + t.estimated_hours,
            0,
          ),
          estimate_notice: "Illustrative estimate.",
        };

        return reply(plan);
      }

      return unavailable();
    }

    if (parts[0] === "engineering-tasks") {
      const task = data.tasks.find((t) => t.id === parts[1]);

      if (!task) return reply({ detail: "Sample task not found." }, 404);

      const job =
        data.jobs.find((j) => j.snapshot.run_id === task.execution_run_id) ??
        null;

      const history = links(task);

      const current =
        history.find((l) => l.execution_task_id === job?.id) ?? null;

      const owner = data.members.find((m) => m.id === task.assignee_id) ?? null;

      if (read && parts.length === 2) return reply(task);

      if (read && parts[2] === "execution")
        return reply({
          task,
          owner,
          execution_owner: owner,
          current,
          execution: job,
          history,
          can_accept: job?.phase === "succeeded" && task.status === "review",
          can_request_changes:
            job?.phase === "succeeded" && task.status === "review",
          acceptance_evidence:
            job?.phase === "succeeded" ? fixture.evidence(task) : null,
          eligibility: {
            can_start: false,
            reasons: ["Public showcase: real execution is unavailable."],
            active_execution_count: 0,
            max_concurrent_executions: 1,
            dependencies: task.dependencies
              .map((d) => data.tasks.find((t) => t.id === d.task_id))
              .filter(Boolean),
          },
        });

      if (read && parts[2] === "executions")
        return reply({ executions: history });

      if (read && parts[2] === "recommendations")
        return reply({
          recommendations: [],
          warnings: ["Assignment recommendations require the local runtime."],
          project_revision: 1,
          workspace_revision: 1,
        });

      if (parts[2] === "assignment" && ["POST", "DELETE"].includes(method)) {
        task.assignee_id = method === "DELETE" ? null : body.assignee_id;
        task.squad_id = method === "DELETE" ? null : body.squad_id;
        task.revision++;

        return reply({ task, warnings: [] });
      }

      if (
        parts[2] === "status" &&
        method === "PATCH" &&
        !task.execution_run_id
      ) {
        task.status = body.status;
        task.revision++;
        return reply(task);
      }

      if (
        parts[2] === "accept" &&
        method === "POST" &&
        job?.phase === "succeeded" &&
        task.status === "review"
      ) {
        if (!body.unresolved_acknowledged)
          return reply(
            {
              detail:
                "Acknowledge unresolved sample criteria before accepting.",
            },
            409,
          );

        decisions.set(job.id, "accepted");
        task.status = "done";
        task.revision++;
        return reply({ task });
      }

      if (read && parts[2] === "preview")
        return reply({
          profile: data.profile,
          can_start: false,
          reason:
            "Public showcase: Docker previews cannot be started. This retained log illustrates an isolated environment.",
          current: {
            id: "sample-preview",
            execution_task_id: job?.id,
            run_id: job?.snapshot.run_id ?? "sample",
            status: "stopped",
            preview_url: null,
            base_url: null,
            ready_at: fixture.date,
            expires_at: "2026-10-28T10:30:00Z",
            logs: "ILLUSTRATIVE PREVIEW LOG\nSource copied to isolated volume\nHealth check /health: 200\nEnvironment stopped; no live container exists",
            failure_reason: null,
            profile: data.profile,
          },
          history: [],
        });

      return unavailable();
    }

    if (parts[0] === "tasks" && read) {
      if (["delivery", "archive"].includes(parts[2])) return unavailable();
      const job = data.jobs.find((j) => j.id === parts[1]);

      if (!job) return reply({ detail: "Sample run not found." }, 404);

      if (parts.length === 2) return reply(job);

      if (parts[2] === "acceptance-evidence")
        return reply(
          job.id.endsWith("previous")
            ? {
                state: "not_generated",
                version: null,
                mapper_version: null,
                error: null,
                counts: null,
                criteria: [],
                acceptance: null,
              }
            : fixture.evidence(
                data.tasks.find(
                  (t) => t.id === job.engineering_origin?.engineering_task_id,
                )!,
              ),
        );

      if (parts[2] === "files")
        return reply({ run_id: job.snapshot.run_id, files: previewFiles });

      if (parts[2] === "file") {
        const file = url.searchParams.get("path");

        if (!previewFiles.includes(file ?? ""))
          return reply({ detail: "Sample file not found." }, 404);

        const sources: Record<string, string> = {
          "src/auth/security.py":
            "from datetime import datetime, timedelta, timezone\n\ndef token_expiry(ttl_minutes: int) -> datetime:\n    return datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)\n",

          "tests/test_auth.py":
            'from app import client\n\ndef test_login_response():\n    response = client.post("/login", json={"username": "example"})\n    assert response.json()["token_type"] == "bearer"\n',

          "src/auth/schemas.py":
            'from pydantic import BaseModel\n\nclass TokenResponse(BaseModel):\n    access_token: str\n    token_type: str = "bearer"\n',

          "src/auth/routes.py":
            '# Illustrative retained excerpt; dependencies are outside this view.\n@router.post("/login")\ndef login(credentials: LoginRequest):\n    user = authenticate(credentials)\n    token = create_access_token(user.id)\n    return {\n        "access_token": token,\n        "token_type": "bearer",\n    }\n',
        };

        if (!sources[file!])
          return reply(
            {
              detail:
                "Only changed source excerpts are retained in this showcase.",
            },
            404,
          );

        const content = sources[file!];

        return reply({ content });
      }
    }

    if (parts[0] === "system" && parts[1] === "models") {
      const connections = [
        {
          id: "sample-nvidia",
          revision: 1,
          name: "NVIDIA NIM · sample",
          protocol: "nvidia",
          base_url: "https://integrate.api.nvidia.com/v1",
          has_key: false,
          structured_mode: "prompt",
          token_parameter: "max_tokens",
          send_temperature: true,
          reasoning_policy: "provider_default",
        },
        {
          id: "sample-ollama",
          revision: 1,
          name: "Ollama · sample fallback",
          protocol: "ollama",
          base_url: "http://127.0.0.1:11434",
          has_key: false,
          structured_mode: "prompt",
          token_parameter: "max_tokens",
          send_temperature: true,
          reasoning_policy: "provider_default",
        },
      ];

      if (read && parts[2] === "settings")
        return reply({
          connections,
          route: {
            primary_connection: connections[0].id,
            primary_model: "moonshotai/kimi-k3",
            fallback_enabled: true,
            fallback_connection: connections[1].id,
            fallback_model: "qwen2.5-coder:3b",
          },
          revision: 1,
          locked: true,
        });

      if (read && parts.length === 2)
        return reply({
          primary: {
            display_name: connections[0].name,
            model: "moonshotai/kimi-k3",
            effective_reasoning: "Low · Kimi legacy default",
            reasoning_source: "Sample configuration",
          },
          fallback: {
            display_name: connections[1].name,
            model: "qwen2.5-coder:3b",
            enabled: true,
          },
          configuration_source:
            "Showcase fixture · no connections or credentials",
          request_timeout_seconds: 180,
        });

      return unavailable();
    }

    return read
      ? reply({ detail: "This record is unavailable in the showcase." }, 404)
      : unavailable();
  };
}
