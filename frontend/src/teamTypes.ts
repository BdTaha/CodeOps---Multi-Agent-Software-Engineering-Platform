import type { EngineeringTask } from './productTypes';
export const technicalAreas = ['Backend', 'Frontend', 'Database', 'DevOps', 'QA', 'General'];
export interface SquadInput { name: string; description: string; technical_areas: string[] }
export interface Squad extends SquadInput { id: string; project_id: string; revision: number; created_at: string }
export interface MemberInput {
  name: string; role: string; member_type: 'human' | 'ai'; squad_id: string;
  skills: { technical_area: string; proficiency: number }[]; active: boolean;
  weekly_capacity_hours: number | null; target_utilization: number | null;
  availability: 'available' | 'busy' | 'offline' | null; max_concurrent_tasks: number | null;
  future_execution_role: 'developer' | 'tester' | 'reviewer' | 'general' | null;
}
export interface TeamMember extends MemberInput { id: string; project_id: string; revision: number; created_at: string }
export interface MemberCapacity {
  member_id: string; planned_load_hours: number; assigned_task_count: number;
  assignable_capacity_hours: number | null; reserved_capacity_hours: number | null;
  remaining_capacity_hours: number | null; remaining_task_slots: number | null;
}
export interface TeamSnapshot { squads: Squad[]; members: TeamMember[]; tasks: EngineeringTask[]; capacities: MemberCapacity[]; project_revision: number; current_plan_id: string | null }
export interface Recommendation {
  task_id: string; member_id: string; squad_id: string; score: number; skill_proficiency: number;
  fits_capacity: boolean; reasons: string[]; warnings: string[];
  remaining_capacity_hours: number | null; remaining_task_slots: number | null;
}
export interface TaskRecommendations { recommendations: Recommendation[]; warnings: string[]; project_revision: number }
export interface SuggestedPlan {
  project_revision: number;
  suggestions: { task_id: string; key: string; title: string; assignee_id: string; squad_id: string; revision: number; reasons: string[]; warnings: string[] }[];
  unfilled: { task_id: string; key: string; reason: string }[];
}
