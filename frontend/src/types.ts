export type View = 'projects' | 'workspace' | 'review' | 'results';
export type Agent = 'supervisor' | 'repository_analyzer' | 'planner' | 'developer' | 'tester' | 'reviewer';
export type Status = 'waiting' | 'running' | 'succeeded' | 'failed' | 'approval' | 'unavailable' | 'skipped';
export interface Project { id: string; name: string; path: string; description: string; stack: string[] }
export interface Execution { execution_id: string; agent: string; operation: string; status: string; input_summary: string; output_summary: string; duration_seconds: number; started_at: string; ended_at: string; attempt: number; error?: { code: string; message: string } | null }
export interface Plan { problem_interpretation: string; steps: { description: string; files: string[] }[]; risks: string[]; tests_to_run: string[]; context_files: string[]; limitations: string[] }
export interface Change { path: string; kind: string; summary: string }
export interface Snapshot {
  run_id: string; task: { task_id: string; status: string; request: { repository_path: string; user_request: string } };
  workspace_path: string | null; development_attempts: number;
  analysis: { languages: string[]; frameworks: string[]; dependencies: string[]; architecture_summary: string; important_files: string[]; relevant_files: string[]; inspected_file_count: number; limitations: string[] } | null;
  plan: Plan | null; development: { diff: string; changes: Change[]; explanation: string; limitations: string[]; approval_id: string } | null;
  changes: Change[]; executions: Execution[]; errors: { code: string; message: string }[];
  tests: { outcome: string; summary: string; counts: { passed: number; failed: number; skipped: number } | null; executions: { command: string[]; exit_code: number | null; output_summary: string }[] } | null;
  review: { approved: boolean; summary: string; findings: { file?: string; line?: number; description: string; severity: string; recommended_fix?: string; evidence?: string | null }[] } | null;
  report: { summary: string; limitations: string[] } | null;
}
export interface ProgressEvent { kind: string; node?: string; snapshot?: Snapshot; message?: string }
export interface FileList { run_id: string; files: string[] }
export interface Approval { approval_id: string | null; run_id?: string; plan?: Plan }
export const agents: { id: Agent; name: string; short: string; description: string; operation: string }[] = [
  { id: 'supervisor', name: 'Supervisor', short: 'S', description: 'Coordinates the engineering task', operation: 'initialize_task' },
  { id: 'repository_analyzer', name: 'Repository Analyzer', short: 'A', description: 'Maps architecture and relevant files', operation: 'analyze_repository' },
  { id: 'planner', name: 'Planner', short: 'P', description: 'Turns the request into a focused plan', operation: 'plan_implementation' },
  { id: 'developer', name: 'Developer', short: 'D', description: 'Applies approved changes to the snapshot', operation: 'develop_implementation' },
  { id: 'tester', name: 'Test Agent', short: 'T', description: 'Runs tests and investigates failures', operation: 'run_tests' },
  { id: 'reviewer', name: 'Reviewer', short: 'R', description: 'Reviews correctness and code quality', operation: 'review_changes' },
];
