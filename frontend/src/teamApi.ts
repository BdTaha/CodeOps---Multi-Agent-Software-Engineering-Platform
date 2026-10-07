import { request } from './productApi';
import type { EngineeringTask } from './productTypes';
import type { Squad, SquadInput, TeamMember, MemberInput, TeamSnapshot, TaskRecommendations, SuggestedPlan } from './teamTypes';
export const getTeams = (projectId: string) => request<TeamSnapshot>(`/projects/${projectId}/teams`);
export const saveSquad = (projectId: string, body: SquadInput, existing?: Squad) => existing
  ? request<Squad>(`/squads/${existing.id}`, 'PATCH', { ...body, revision: existing.revision })
  : request<Squad>(`/projects/${projectId}/squads`, 'POST', body);
export const saveMember = (projectId: string, body: MemberInput, existing?: TeamMember) => existing
  ? request<TeamMember>(`/members/${existing.id}`, 'PATCH', { ...body, revision: existing.revision })
  : request<TeamMember>(`/projects/${projectId}/members`, 'POST', body);
export const assignTask = (task: EngineeringTask, squadId: string, memberId: string, override = false) =>
  request<{ task: EngineeringTask; warnings: string[] }>(`/engineering-tasks/${task.id}/assignment`, 'POST', {
    squad_id: squadId || null, assignee_id: memberId || null, revision: task.revision, override_warnings: override,
  });
export const unassignTask = (task: EngineeringTask) => request<{ task: EngineeringTask; warnings: string[] }>(`/engineering-tasks/${task.id}/assignment?revision=${task.revision}`, 'DELETE');
export const getRecommendations = (taskId: string) => request<TaskRecommendations>(`/engineering-tasks/${taskId}/recommendations`);
export const suggestAssignments = (projectId: string) => request<SuggestedPlan>(`/projects/${projectId}/assignment-recommendations`);
export const applySuggestions = (projectId: string, plan: SuggestedPlan) => request<TeamSnapshot>(`/projects/${projectId}/apply-assignment-recommendations`, 'POST', {
  project_revision: plan.project_revision, assignments: plan.suggestions.map(({task_id, assignee_id, revision}) => ({task_id, assignee_id, revision})),
});
