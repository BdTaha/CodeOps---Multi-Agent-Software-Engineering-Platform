import type { EngineeringTask } from './productTypes';
export const technicalAreas = ['Backend', 'Frontend', 'Database', 'DevOps', 'QA', 'General'];
export interface SquadInput { name: string; description: string; technical_areas: string[] }
export interface Squad extends SquadInput { id: string; project_id: string; revision: number; created_at: string }
export interface MemberInput {
  name: string; role: string; member_type: 'human' | 'ai';
  skills: { technical_area: string; proficiency: number }[]; active: boolean;
  weekly_capacity_hours: number | null; target_utilization: number | null;
  availability: 'available' | 'busy' | 'offline' | null; max_concurrent_executions: number | null;
  future_execution_role: 'developer' | 'tester' | 'reviewer' | 'general' | null;
}
export interface TeamMember extends MemberInput { id: string; revision: number; created_at: string }
export interface ProjectMembership { id: string; project_id: string; member_id: string; squad_id: string; active: boolean; revision: number; created_at: string }
export interface MemberCapacity {
  member_id: string; planned_load_hours: number | null; assigned_task_count: number;
  assignable_capacity_hours: number | null; reserved_capacity_hours: number | null;
  remaining_capacity_hours: number | null; assigned_queue_depth: number | null; max_concurrent_executions: number | null;
  active_execution_count: number | null; runtime_connected: boolean;
  project_breakdown: { project_id: string; project_name: string; planned_load_hours: number | null; assigned_task_count: number }[];
}
export interface WorkspaceSnapshot { members: TeamMember[]; memberships: ProjectMembership[]; tasks: EngineeringTask[]; capacities: MemberCapacity[]; projects: {id: string; name: string}[]; workspace_revision: number }
export interface TeamSnapshot { squads: Squad[]; members: TeamMember[]; tasks: EngineeringTask[]; capacities: MemberCapacity[]; project_revision: number; current_plan_id: string | null; workspace_revision: number; memberships: ProjectMembership[]; workspace_members: TeamMember[]; workspace_memberships: ProjectMembership[]; workspace_tasks: EngineeringTask[]; projects: {id: string; name: string}[] }
export interface Recommendation {
  task_id: string; member_id: string; squad_id: string; score: number; skill_proficiency: number;
  fits_capacity: boolean; reasons: string[]; warnings: string[];
  remaining_capacity_hours: number | null; assigned_queue_depth: number | null;
}
export interface TaskRecommendations { recommendations: Recommendation[]; warnings: string[]; project_revision: number; workspace_revision: number }
export interface SuggestedPlan {
  project_revision: number;
  workspace_revision: number;
  suggestions: { task_id: string; key: string; title: string; assignee_id: string; squad_id: string; revision: number; reasons: string[]; warnings: string[] }[];
  unfilled: { task_id: string; key: string; reason: string }[];
}
