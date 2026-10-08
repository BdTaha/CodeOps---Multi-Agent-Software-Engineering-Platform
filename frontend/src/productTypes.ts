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
  model_invocations?:import('./types').ModelInvocation[];
  goal: { id: string; project_id: string; goal: string; created_at: string };
  status: 'queued' | 'generating' | 'draft' | 'approved' | 'ready' | 'failed'; plan: ProjectPlan | null;
  attempts: number; error: string | null; model: string | null;
  draft?: ProductPlanDraft | null; draft_revision?: number | null;
  planning_basis?: PlanningBasis | null; materialization?: Record<string,string>;
  approved_at?: string | null; legacy_approved?: boolean;
}
export interface ProductPlanDraft {
  title:string; summary:string; assumptions:string[];
  epics:{ref:string;title:string;description:string}[];
  tasks:{ref:string;epic_ref:string;title:string;description:string;priority:EngineeringTask['priority'];estimated_hours:number;technical_area:string;dependencies:string[];acceptance_criteria:{description:string}[]}[];
}
export interface PlanningBasis {
  mode:'repository_grounded'|'goal_only';reason:string|null;inspected_files:string[];limitations:string[];
  analysis:{architecture_summary:string;languages:string[];frameworks:string[];dependencies:string[];top_level_directories:string[];limitations:string[]}|null;
}
export const boardColumns: { status: EngineeringStatus; label: string }[] = [
  { status: 'backlog', label: 'Backlog' }, { status: 'planned', label: 'Planned' },
  { status: 'in_progress', label: 'In progress' }, { status: 'review', label: 'Review' },
  { status: 'done', label: 'Done' },
];
