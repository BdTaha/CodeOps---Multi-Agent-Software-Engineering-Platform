import type { EngineeringStatus, EngineeringTask, PlanRecord } from './productTypes';

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, { method, cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}
export const getPlan = (projectId: string) => request<PlanRecord | null>(`/projects/${projectId}/plan`);
export const createPlan = (projectId: string, goal: string) => request<PlanRecord>(`/projects/${projectId}/plans`, 'POST', { goal });
export const getEngineeringTask = (taskId: string) => request<EngineeringTask>(`/engineering-tasks/${taskId}`);
export const setTaskStatus = (task: EngineeringTask, status: EngineeringStatus) =>
  request<EngineeringTask>(`/engineering-tasks/${task.id}/status`, 'PATCH', { status, revision: task.revision });
