const { test } = require("node:test");
const assert = require("node:assert/strict");
const { createShowcaseApi } = require("../.test-dist/showcase/showcaseApi");

test("showcase never falls through to HTTP, including unknown and dangerous actions", async () => {
  const original = global.fetch;
  global.fetch = () => {
    throw new Error("Network must never be used");
  };
  try {
    const api = createShowcaseApi();
    for (const path of [
      "/projects",
      "/workspace/teams",
      "/system/models/settings",
      "/tasks?details=false",
    ])
      assert.equal((await api(path)).status, 200);
    for (const path of [
      "/tasks",
      "/projects/import",
      "/tasks/showcase-job-17/delivery",
      "/tasks/showcase-job-18/approve",
      "/engineering-tasks/showcase-task-17/request-changes",
      "/system/models/connections/sample-nvidia/test",
      "/previews/sample-preview/restart",
    ]) {
      const result = await api(path, {
        method: "POST",
        body: JSON.stringify({
          api_key: "do-not-send",
          repository_path: "do-not-touch",
        }),
      });
      assert.equal(result.status, 403, path);
    }
    assert.equal((await api("/unknown")).status, 404);
    assert.equal((await api("/tasks/showcase-job-17/delivery")).status, 403);
  } finally {
    global.fetch = original;
  }
});
test("sample product draft saves and requires explicit approval before Board tasks exist", async () => {
  const api = createShowcaseApi();
  const board = async () =>
    (await (await api("/projects/showcase-api/engineering-tasks")).json())
      .tasks;
  const before = (await board()).length;
  const draft = await (await api("/projects/showcase-api/plan")).json();
  draft.draft.title = "Reviewed reservation plan";
  const saved = await (
    await api("/product-plans/showcase-draft/draft", {
      method: "PUT",
      body: JSON.stringify({ revision: 0, draft: draft.draft }),
    })
  ).json();
  assert.equal(saved.draft_revision, 1);
  assert.equal((await board()).length, before);
  const stale = await api("/product-plans/showcase-draft/approve", {
    method: "POST",
    body: JSON.stringify({ revision: 0 }),
  });
  assert.equal(stale.status, 403);
  const approved = await (
    await api("/product-plans/showcase-draft/approve", {
      method: "POST",
      body: JSON.stringify({ revision: 1 }),
    })
  ).json();
  assert.equal(approved.status, "approved");
  assert.equal((await board()).length, before + 2);
  assert.equal((await board()).at(-1).execution_run_id, null);
  const historical = await (
    await api("/product-plans/showcase-approved")
  ).json();
  assert.equal(historical.plan.tasks.length, before);
});
test("historical sample run never borrows current evidence and state resets per visitor", async () => {
  const api = createShowcaseApi();
  const historical = await (
    await api("/tasks/showcase-job-17-previous/acceptance-evidence")
  ).json();
  assert.equal(historical.state, "not_generated");
  const state = await (
    await api("/engineering-tasks/showcase-task-17/execution")
  ).json();
  assert.equal(state.task.status, "review");
  assert.equal(state.can_accept, true);
  assert.deepEqual(
    state.acceptance_evidence.criteria.map((c) => c.verification_status),
    ["verified", "supported", "unverified"],
  );
  assert.equal(
    (
      await api("/engineering-tasks/showcase-task-17/accept", {
        method: "POST",
        body: "{}",
      })
    ).status,
    409,
  );
  assert.equal(
    (
      await api("/engineering-tasks/showcase-task-17/accept", {
        method: "POST",
        body: JSON.stringify({ unresolved_acknowledged: true }),
      })
    ).status,
    200,
  );
  const fresh = await (
    await createShowcaseApi()("/engineering-tasks/showcase-task-17/execution")
  ).json();
  assert.equal(fresh.task.status, "review");
});
test("normal HTTP transport retains request method and exact same-origin path", async () => {
  const { apiFetch } = require("../.test-dist/transport");
  const original = global.fetch;
  let observed;
  global.fetch = async (path, init) => {
    observed = { path, init };
    return Response.json({ ok: true });
  };
  try {
    await apiFetch("/engineering-tasks/retained-task/accept", {
      method: "POST",
      body: '{"revision":2}',
    });
    assert.deepEqual(observed, {
      path: "/engineering-tasks/retained-task/accept",
      init: { method: "POST", body: '{"revision":2}' },
    });
  } finally {
    global.fetch = original;
  }
});
