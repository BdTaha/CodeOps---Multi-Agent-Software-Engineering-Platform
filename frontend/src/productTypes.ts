export type EngineeringStatus = 'backlog' | 'planned' | 'in_progress' | 'review' | 'done';
export interface EngineeringTask {
  id: string; key: string; project_id: string; plan_id: string; epic_id: string;
  title: string; description: string; status: EngineeringStatus;
  priority: 'low' | 'medium' | 'high' | 'urgent'; estimated_hours: number;
  technical_area: string; dependencies: { task_id: string }[];
  acceptance_criteria: { id:string; description: string }[]; created_at: string;
  revision: number; execution_run_id: string | null;
  squad_id: string | null; assignee_id: string | null;
}
export interface ProjectPlan {
  id: string; project_id: string; title: string; summary: string; assumptions: string[];
  epics: { id: string; plan_id: string; title: string; description: string }[];
  tasks: EngineeringTask[]; estimated_hours: number; estimate_notice: string;
}
export interface PlanRecord {
  goal: { id: string; project_id: string; goal: string; created_at: string };
  status: 'queued' | 'generating' | 'ready' | 'failed'; plan: ProjectPlan | null;
  attempts: number; error: string | null; model: string | null;
}
export const boardColumns: { status: EngineeringStatus; label: string }[] = [
  { status: 'backlog', label: 'Backlog' }, { status: 'planned', label: 'Planned' },
  { status: 'in_progress', label: 'In progress' }, { status: 'review', label: 'Review' },
  { status: 'done', label: 'Done' },
];
