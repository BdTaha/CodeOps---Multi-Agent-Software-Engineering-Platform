/** Deterministic illustrative records. No provider or test runner executed these. */
import type { Project, Snapshot } from "../../types";
import type {
  EngineeringTask,
  PlanRecord,
  ProductPlanDraft,
} from "../../productTypes";
import type {
  TeamMember,
  Squad,
  ProjectMembership,
  MemberCapacity,
} from "../../teamTypes";
import type { Job } from "../../api";
import type { AcceptanceEvidence } from "../../AcceptanceEvidence";
import type { PreviewProfile } from "../../PreviewSettings";
import { previewSnapshot } from "../../preview";

export const date = "2026-10-28T10:00:00Z";
export const projects: Project[] = [
  {
    id: "showcase-api",
    name: "Meridian API",
    path: "showcase://meridian-api",
    description: "Inventory and fulfillment service · illustrative repository",
    stack: ["Python", "FastAPI", "PostgreSQL"],
  },
  {
    id: "showcase-console",
    name: "Meridian Console",
    path: "showcase://meridian-console",
    description:
      "Operations console for warehouse teams · illustrative repository",
    stack: ["React", "TypeScript", "Vite"],
  },
];
const titles = [
  "Enforce scoped access tokens",
  "Reject expired session tokens",
  "Add idempotent inventory reservations",
  "Expose reservation health checks",
  "Document fulfillment API contracts",
  "Add stock movement audit trail",
  "Cover concurrent reservation conflicts",
];
const statuses = [
  "review",
  "in_progress",
  "planned",
  "planned",
  "done",
  "backlog",
  "backlog",
] as const;
export const tasks: EngineeringTask[] = titles.map((title, i) => ({
  id: `showcase-task-${i + 17}`,
  key: `CO-${i + 17}`,
  project_id: projects[0].id,
  plan_id: "showcase-approved",
  epic_id: i < 2 ? "access" : "inventory",
  title,
  description:
    i === 0
      ? "Issue scoped bearer tokens through the existing login route. Keep public catalog endpoints accessible and reject expired credentials."
      : `${title} within the existing service boundaries. Preserve current API contracts and add focused regression coverage.`,
  status: statuses[i],
  priority: i < 3 ? "high" : "medium",
  estimated_hours: [4, 2, 5, 2, 1, 4, 3][i],
  technical_area: i === 4 ? "General" : i === 6 ? "QA" : "Backend",
  dependencies: i === 6 ? [{ task_id: "showcase-task-19" }] : [],
  acceptance_criteria: (i === 0
    ? [
        "Login returns a bearer token.",
        "Token lifetime is configurable.",
        "Public catalog access remains unchanged.",
      ]
    : [`${title} has focused regression coverage.`]
  ).map((description, n) => ({ id: `criterion-${i}-${n}`, description })),
  created_at: date,
  revision: 1,
  execution_run_id: i < 2 ? `showcase-run-${i + 17}` : null,
  squad_id: i < 5 ? "platform" : null,
  assignee_id: i < 4 ? "agent-backend" : i === 4 ? "maintainer" : null,
}));
export const members: TeamMember[] = [
  {
    id: "agent-backend",
    name: "Backend developer",
    role: "API implementation",
    member_type: "ai",
    skills: [
      { technical_area: "Backend", proficiency: 5 },
      { technical_area: "Database", proficiency: 4 },
    ],
    active: true,
    weekly_capacity_hours: null,
    target_utilization: null,
    availability: "available",
    max_concurrent_executions: 1,
    future_execution_role: "developer",
    revision: 1,
    created_at: date,
  },
  {
    id: "agent-tests",
    name: "Quality developer",
    role: "Regression coverage",
    member_type: "ai",
    skills: [{ technical_area: "QA", proficiency: 5 }],
    active: true,
    weekly_capacity_hours: null,
    target_utilization: null,
    availability: "available",
    max_concurrent_executions: 1,
    future_execution_role: "developer",
    revision: 1,
    created_at: date,
  },
  {
    id: "maintainer",
    name: "Project maintainer",
    role: "Technical lead",
    member_type: "human",
    skills: [{ technical_area: "Backend", proficiency: 5 }],
    active: true,
    weekly_capacity_hours: 32,
    target_utilization: 0.75,
    availability: null,
    max_concurrent_executions: null,
    future_execution_role: null,
    revision: 1,
    created_at: date,
  },
];
export const squads: Squad[] = [
  {
    id: "platform",
    project_id: projects[0].id,
    name: "Platform",
    description: "Service contracts, access control and inventory integrity",
    technical_areas: ["Backend", "Database", "QA"],
    revision: 1,
    created_at: date,
  },
];
export const memberships: ProjectMembership[] = members.map((m) => ({
  id: `membership-${m.id}`,
  project_id: projects[0].id,
  member_id: m.id,
  squad_id: "platform",
  active: true,
  revision: 1,
  created_at: date,
}));
export function capacities(currentTasks = tasks): MemberCapacity[] {
  return members.map((m) => ({
    member_id: m.id,
    planned_load_hours: m.member_type === "human" ? 1 : null,
    assigned_task_count: currentTasks.filter((t) => t.assignee_id === m.id)
      .length,
    assignable_capacity_hours: m.member_type === "human" ? 24 : null,
    reserved_capacity_hours: m.member_type === "human" ? 8 : null,
    remaining_capacity_hours: m.member_type === "human" ? 23 : null,
    assigned_queue_depth:
      m.member_type === "ai"
        ? currentTasks.filter(
            (t) => t.assignee_id === m.id && t.status !== "done",
          ).length
        : null,
    max_concurrent_executions: m.max_concurrent_executions,
    active_execution_count: m.id === "agent-backend" ? 1 : 0,
    runtime_connected: m.member_type === "ai",
    active_executions:
      m.id === "agent-backend"
        ? [
            {
              ai_member_id: m.id,
              engineering_task_id: tasks[1].id,
              execution_task_id: "showcase-job-18",
              phase: "awaiting_approval",
            },
          ]
        : [],
    project_breakdown: [
      {
        project_id: projects[0].id,
        project_name: projects[0].name,
        planned_load_hours: m.member_type === "human" ? 1 : null,
        assigned_task_count: currentTasks.filter((t) => t.assignee_id === m.id)
          .length,
      },
    ],
  }));
}

export const draft: ProductPlanDraft = {
  title: "Reservation integrity",
  summary:
    "Make inventory reservations safe to retry and straightforward to diagnose.",
  assumptions: ["One service owns reservation writes."],
  epics: [
    {
      ref: "E1",
      title: "Reliable reservations",
      description: "Idempotency and observable failures.",
    },
  ],
  tasks: [
    {
      ref: "T1",
      epic_ref: "E1",
      title: "Validate idempotency keys",
      description:
        "Bind retry keys to the request payload and reject conflicting reuse.",
      priority: "high",
      estimated_hours: 3,
      technical_area: "Backend",
      dependencies: [],
      acceptance_criteria: [
        {
          description:
            "Repeated identical requests return the original reservation.",
        },
      ],
    },
    {
      ref: "T2",
      epic_ref: "E1",
      title: "Document retry behavior",
      description: "Describe conflict responses and safe client retries.",
      priority: "medium",
      estimated_hours: 1,
      technical_area: "General",
      dependencies: ["T1"],
      acceptance_criteria: [
        { description: "API documentation includes a retry example." },
      ],
    },
  ],
};
export const approvedPlan: PlanRecord = {
  goal: {
    id: "showcase-approved",
    project_id: projects[0].id,
    goal: "Harden access control and inventory reservation boundaries.",
    created_at: date,
  },
  status: "approved",
  attempts: 1,
  error: null,
  model: "Illustrative model",
  plan: {
    id: "showcase-approved",
    project_id: projects[0].id,
    title: "Service reliability",
    summary: "Scoped access and predictable inventory operations.",
    assumptions: [],
    epics: [
      {
        id: "access",
        plan_id: "showcase-approved",
        title: "Access control",
        description: "Scoped, expiring sessions",
      },
      {
        id: "inventory",
        plan_id: "showcase-approved",
        title: "Inventory integrity",
        description: "Safe reservation workflows",
      },
    ],
    tasks: structuredClone(tasks),
    estimated_hours: 21,
    estimate_notice: "Illustrative effort estimates, not delivery promises.",
  },
};
export const draftPlan: PlanRecord = {
  goal: {
    id: "showcase-draft",
    project_id: projects[0].id,
    goal: "Make reservation requests safe to retry without allocating stock twice.",
    created_at: date,
  },
  status: "draft",
  attempts: 1,
  error: null,
  model: "Illustrative model",
  plan: null,
  draft,
  draft_revision: 0,
  planning_basis: {
    mode: "repository_grounded",
    reason: null,
    inspected_files: [
      "src/reservations/service.py",
      "src/inventory/repository.py",
      "tests/test_reservations.py",
    ],
    limitations: ["Showcase fixture: no repository was inspected."],
    analysis: {
      architecture_summary:
        "Illustrative FastAPI service with transactional reservation writes and a separate catalog read path.",
      languages: ["Python"],
      frameworks: ["FastAPI"],
      dependencies: ["SQLAlchemy", "Pydantic"],
      top_level_directories: ["src", "tests"],
      limitations: [],
    },
  },
};

function snapshot(task: EngineeringTask): Snapshot {
  const result = structuredClone(previewSnapshot);
  result.run_id = `showcase-run-${task.key.slice(3)}`;
  result.task = {
    task_id: `showcase-job-${task.key.slice(3)}`,
    status: "succeeded",
    request: {
      repository_path: projects[0].path,
      user_request: task.description,
    },
  };
  result.analysis!.architecture_summary =
    "Illustrative service with authentication, inventory and fulfillment modules.";
  result.tests = {
    outcome: "passed",
    summary:
      "Sample test report for exploring the interface. No tests were executed by the showcase.",
    counts: { passed: 4, failed: 0, skipped: 0 },
    executions: [
      {
        command: ["python", "-m", "pytest", "tests/test_auth.py", "-q"],
        exit_code: 0,
        duration_seconds: 1.8,
        output_summary:
          "ILLUSTRATIVE TEST OUTPUT\ntest_login_response PASSED\ntest_expired_token PASSED\ntest_malformed_token PASSED\ntest_public_catalog PASSED\n4 passed in 1.80s",
      },
    ],
  };
  return result;
}
export const jobs: Job[] = [tasks[0], tasks[1]].map((task, i) => {
  const s = snapshot(task);
  if (i === 1) {
    s.task.status = "running";
    s.development = null;
    s.development_attempts = 0;
    s.changes = [];
    s.tests = null;
    s.review = null;
    s.report = null;
    s.executions = s.executions.slice(0, 3);
  }
  if (i === 1)
    s.plan = {
      problem_interpretation:
        "Reject expired session tokens at the existing authentication boundary while preserving public catalog access.",
      steps: [
        {
          description:
            "Validate token expiry with a timezone-aware comparison and the existing unauthorized response.",
          files: ["src/auth/security.py"],
        },
        {
          description:
            "Cover expired, malformed and valid tokens without changing public route behavior.",
          files: ["tests/test_auth.py"],
        },
      ],
      risks: ["Preserve the existing unauthorized response contract."],
      tests_to_run: ["python -m pytest tests/test_auth.py -q"],
      context_files: ["src/auth/security.py", "tests/test_auth.py"],
      limitations: [
        "Illustrative plan. No repository was inspected or modified.",
      ],
    };
  return {
    id: s.task.task_id,
    revision: 1,
    created: 1793181600,
    engineering_origin: { engineering_task_id: task.id },
    artifacts_loaded: true,
    phase: i === 1 ? "awaiting_approval" : "succeeded",
    node: null,
    approval: i === 1 ? "showcase-approval" : null,
    snapshot: s,
    cancel: 0,
    options: { test_backend: "docker", framework: "pytest", max_attempts: 3 },
    delivery: {},
  };
});
const previous = structuredClone(jobs[0]);
previous.id = "showcase-job-17-previous";
previous.snapshot.task.task_id = previous.id;
previous.snapshot.run_id = "showcase-run-17-previous";
previous.snapshot.review = {
  approved: false,
  summary: "Illustrative earlier review: token expiry needed focused coverage.",
  findings: [
    {
      severity: "medium",
      file: "tests/test_auth.py",
      description: "Add an expired-token regression before human acceptance.",
    },
  ],
};
previous.phase = "failed";
jobs.push(previous);
previous.snapshot.task.status = "failed";
previous.snapshot.executions.at(-1)!.status = "failed";
previous.snapshot.executions.at(-1)!.output_summary =
  "Illustrative review requested expired-token regression coverage.";
previous.snapshot.report = {
  summary: "Illustrative earlier attempt retained for inspection.",
  limitations: ["Sample artifacts only."],
};

export function evidence(task: EngineeringTask): AcceptanceEvidence {
  return {
    state: "ready",
    version: "showcase-evidence-1",
    mapper_version: "Showcase fixture · illustrative evidence",
    error: null,
    counts: { verified: 1, supported: 1, unverified: 1, conflict: 0 },
    acceptance: null,
    criteria: task.acceptance_criteria.map((c, i) => ({
      criterion_id: c.id,
      description: c.description,
      verification_status:
        i === 0 ? "verified" : i === 1 ? "supported" : "unverified",
      conflict: false,
      evidence:
        i === 2
          ? []
          : [
              {
                id: `sample-evidence-${i}`,
                source_id: `sample-source-${i}`,
                evidence_type: i === 0 ? "automated_test" : "implementation",
                summary:
                  i === 0
                    ? "Illustrative explicit mapping to test_login_response. This is sample evidence, not a test executed by this site."
                    : "Illustrative implementation evidence: expiry is configured in token_expiry.",
                negative: false,
                executed: i === 0,
                mapping: i === 0 ? "explicit" : "semantic",
                reference: {
                  artifact: i === 0 ? "tests" : "diff",
                  test_identifier: i === 0 ? "test_login_response" : undefined,
                  file: i === 1 ? "src/auth/security.py" : undefined,
                  framework: i === 0 ? "pytest" : undefined,
                  outcome: i === 0 ? "passed" : undefined,
                },
              },
            ],
    })),
  };
}
export const profile: PreviewProfile = {
  id: "showcase-profile",
  project_id: projects[0].id,
  revision: 1,
  name: "FastAPI review environment",
  preview_type: "api",
  runtime: "python",
  enabled: true,
  build_commands: [],
  start_command: [
    "uvicorn",
    "src.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
  ],
  container_port: 8000,
  health_path: "/health",
  open_path: "/docs",
  environment: {},
  timeout_seconds: 60,
  ttl_minutes: 30,
  build_network: false,
  requires_external_services: false,
  created_at: date,
};
