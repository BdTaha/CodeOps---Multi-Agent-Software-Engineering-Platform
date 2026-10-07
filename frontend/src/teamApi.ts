import { request } from './productApi';
import type { EngineeringTask } from './productTypes';
import type { Squad, SquadInput, TeamMember, MemberInput, TeamSnapshot, TaskRecommendations, SuggestedPlan, ProjectMembership, WorkspaceSnapshot } from './teamTypes';
export const getTeams = (projectId: string) => request<TeamSnapshot>(`/projects/${projectId}/teams`);
export const saveSquad = (projectId: string, body: SquadInput, existing?: Squad) => existing
  ? request<Squad>(`/squads/${existing.id}`, 'PATCH', { ...body, revision: existing.revision })
  : request<Squad>(`/projects/${projectId}/squads`, 'POST', body);
export const getWorkspace = () => request<WorkspaceSnapshot>('/workspace/teams');
export const saveMember = (body: MemberInput, existing?: TeamMember) => existing
  ? request<TeamMember>(`/workspace/members/${existing.id}`, 'PATCH', { ...body, revision: existing.revision })
  : request<TeamMember>('/workspace/members', 'POST', body);
export const saveMembership = (projectId: string, body: {member_id: string; squad_id: string; active: boolean}, existing?: ProjectMembership) => existing
  ? request<ProjectMembership>(`/project-memberships/${existing.id}`, 'PATCH', {squad_id: body.squad_id, active: body.active, revision: existing.revision})
  : request<ProjectMembership>(`/projects/${projectId}/memberships`, 'POST', body);
export const assignTask = (task: EngineeringTask, squadId: string, memberId: string, override = false) =>
  request<{ task: EngineeringTask; warnings: string[] }>(`/engineering-tasks/${task.id}/assignment`, 'POST', {
    squad_id: squadId || null, assignee_id: memberId || null, revision: task.revision, override_warnings: override,
  });
export const unassignTask = (task: EngineeringTask) => request<{ task: EngineeringTask; warnings: string[] }>(`/engineering-tasks/${task.id}/assignment?revision=${task.revision}`, 'DELETE');
export const getRecommendations = (taskId: string) => request<TaskRecommendations>(`/engineering-tasks/${taskId}/recommendations`);
export const suggestAssignments = (projectId: string) => request<SuggestedPlan>(`/projects/${projectId}/assignment-recommendations`);
export const applySuggestions = (projectId: string, plan: SuggestedPlan) => request<TeamSnapshot>(`/projects/${projectId}/apply-assignment-recommendations`, 'POST', {
  project_revision: plan.project_revision, workspace_revision: plan.workspace_revision, assignments: plan.suggestions.map(({task_id, assignee_id, revision}) => ({task_id, assignee_id, revision})),
});
