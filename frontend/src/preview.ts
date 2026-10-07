/** Illustrative product data only. Never supplied to a live workflow or provider. */
import type { Project, Snapshot } from './types';

export const previewProject: Project = { id: 'preview', name: 'ecommerce-api', path: 'preview://ecommerce-api', description: 'A sample FastAPI service for the product walkthrough.', stack: ['Python', 'FastAPI', 'PostgreSQL'] };
export const previewFiles = ['README.md', 'pyproject.toml', 'src/main.py', 'src/auth/routes.py', 'src/auth/security.py', 'src/auth/schemas.py', 'src/users/service.py', 'src/products/routes.py', 'tests/test_auth.py', 'tests/test_products.py'];
export const previewDiff = `--- a/src/auth/routes.py
+++ b/src/auth/routes.py
@@ -12,4 +12,9 @@
 @router.post("/login")
 def login(credentials: LoginRequest):
     user = authenticate(credentials)
-    return user
+    token = create_access_token(user.id)
+    return {
+        "access_token": token,
+        "token_type": "bearer",
+    }
--- a/src/auth/security.py
+++ b/src/auth/security.py
@@ -1,1 +1,4 @@
 from datetime import datetime, timedelta, timezone
+
+def token_expiry(ttl_minutes: int) -> datetime:
+    return datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
--- a/src/auth/schemas.py
+++ b/src/auth/schemas.py
@@ -1,1 +1,5 @@
 from pydantic import BaseModel
+
+class TokenResponse(BaseModel):
+    access_token: str
+    token_type: str = "bearer"
--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -1,1 +1,5 @@
 from app import client
+
+def test_login_response():
+    response = client.post("/login", json={"username": "example"})
+    assert response.json()["token_type"] == "bearer"
`;
const now = '2026-10-06T10:00:00Z';
const plan = { problem_interpretation: 'Add JWT authentication to the existing FastAPI service while preserving the public product endpoints.', steps: [
  { description: 'Add token generation with configurable expiry and signing settings.', files: ['src/auth/security.py'] },
  { description: 'Return an access token from the existing login endpoint.', files: ['src/auth/routes.py', 'src/auth/schemas.py'] },
  { description: 'Cover valid, expired, and malformed tokens with focused tests.', files: ['tests/test_auth.py'] },
], risks: ['Preserve public endpoint access.', 'Keep signing secrets in environment configuration.'], tests_to_run: ['Run the authentication test suite.', 'Run regression tests for product routes.'], context_files: ['src/auth/routes.py', 'src/auth/security.py', 'tests/test_auth.py'], limitations: ['Illustrative plan for exploring the interface.'] };
export const previewSnapshot: Snapshot = {
  run_id: 'preview-run', task: { task_id: 'preview-task', status: 'succeeded', request: { repository_path: previewProject.path, user_request: 'Add JWT authentication to this FastAPI project.' } },
  workspace_path: null, development_attempts: 2,
  analysis: { languages: ['Python'], frameworks: ['FastAPI'], dependencies: ['FastAPI', 'Pydantic', 'PyJWT'], inspected_file_count: 10, architecture_summary: 'Illustrative FastAPI service organized around authentication, users, and product routes.', important_files: previewFiles, relevant_files: plan.context_files, limitations: ['Preview repository; no files were inspected.'] },
  plan, changes: ['src/auth/routes.py', 'src/auth/security.py', 'src/auth/schemas.py', 'tests/test_auth.py'].map(path => ({ path, kind: 'modified', summary: 'Illustrative authentication change' })),
  development: { diff: previewDiff, explanation: 'Illustrative implementation: added token generation, updated the login response, and covered token validation.', changes: [], limitations: ['Preview changes only. No code was generated or applied.'], approval_id: 'preview' },
  executions: [
    ['supervisor', 'initialize_task', 1.2], ['repository_analyzer', 'analyze_repository', 8.4], ['planner', 'plan_implementation', 14.8], ['developer', 'develop_implementation', 30.6], ['tester', 'run_tests', 10.2], ['developer', 'develop_implementation', 20.1], ['tester', 'run_tests', 9.8], ['reviewer', 'review_changes', 6.9],
  ].map(([agent, operation, duration], i) => ({ execution_id: `preview-${i}`, agent: String(agent), operation: String(operation), status: i === 4 ? 'failed' : 'succeeded', input_summary: 'Illustrative task and repository context.', output_summary: i === 4 ? 'Preview: expired-token test failed; returned to Developer.' : `Preview: ${String(agent)} completed its example operation.`, duration_seconds: Number(duration), attempt: i === 5 || i === 6 ? 2 : 1, started_at: now, ended_at: now, error: i === 4 ? { code: 'PREVIEW_TEST_FAILURE', message: 'Illustrative expired-token failure.' } : null })),
  errors: [], tests: { outcome: 'passed', summary: 'Illustrative results only; no tests were executed.', counts: { passed: 28, failed: 0, skipped: 0 }, executions: [] },
  review: { approved: true, summary: 'Illustrative review: focused implementation with configurable token expiry.', findings: [{ file: 'src/auth/security.py', line: 4, severity: 'low', description: 'Preview comment: keep token expiry configurable.' }] },
  report: { summary: 'Illustrative outcome: JWT authentication added and reviewed after one repair iteration.', limitations: ['All results on this screen are sample data.'] },
};
