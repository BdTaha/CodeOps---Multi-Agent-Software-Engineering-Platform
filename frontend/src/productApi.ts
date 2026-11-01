import type { EngineeringStatus, EngineeringTask, PlanRecord, ProductPlanDraft } from './productTypes';
import { apiFetch } from './transport';

export class AssignmentWarning extends Error {
  constructor(message: string, public warnings: string[]) { super(message); }
}
export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await apiFetch(path, { method, cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    if (error.detail?.warnings) throw new AssignmentWarning(error.detail.message, error.detail.warnings);
    if(Array.isArray(error.detail))throw new Error(error.detail.slice(0,6).map((issue:{loc:string[];msg:string})=>`${issue.loc.join('.')} · ${issue.msg}`).join('; '));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}
export const getPlan = (projectId: string) => request<PlanRecord | null>(`/projects/${projectId}/plan`);
export const createPlan = (projectId: string, goal: string) => request<PlanRecord>(`/projects/${projectId}/plans`, 'POST', { goal });
export const getPlanHistory=(projectId:string)=>request<{plans:PlanRecord[]}>(`/projects/${projectId}/plans`);
export const getSavedPlan=(planId:string)=>request<PlanRecord>(`/product-plans/${planId}`);
export const getApprovedTasks=(projectId:string)=>request<{tasks:EngineeringTask[]}>(`/projects/${projectId}/engineering-tasks`);
export const saveDraft=(record:PlanRecord,draft:ProductPlanDraft)=>request<PlanRecord>(`/product-plans/${record.goal.id}/draft`,'PUT',{revision:record.draft_revision,draft:{...draft,assumptions:draft.assumptions.filter(value=>value.trim())}});
export const approveProductPlan=(record:PlanRecord)=>request<PlanRecord>(`/product-plans/${record.goal.id}/approve`,'POST',{revision:record.draft_revision});
export const getEngineeringTask = (taskId: string) => request<EngineeringTask>(`/engineering-tasks/${taskId}`);
export const setTaskStatus = (task: EngineeringTask, status: EngineeringStatus) =>
  request<EngineeringTask>(`/engineering-tasks/${task.id}/status`, 'PATCH', { status, revision: task.revision });
